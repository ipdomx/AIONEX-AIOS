"""Real publishing to Facebook Pages and Instagram Business through the Graph API.

Facebook Page: text and link posts (``/{page}/feed``), a single photo
(``/{page}/photos``), multi-photo posts (unpublished photo uploads attached
to one ``/{page}/feed`` post) and videos (``/{page}/videos`` with
``file_url``). Instagram: image, carousel and video/Reels through the
container flow (``/{ig}/media`` then ``/{ig}/media_publish``) with
``status_code`` polling until the container is ``FINISHED``.

Every call is pinned to ``META_GRAPH_API_VERSION`` and carries
``appsecret_proof``. Success is reported only with the id Graph returned;
anything else is a ``GraphPublishError`` classified as transient (safe to
retry), permanent, token-expired, or ambiguous (the request may have created
the post, so it must never be replayed automatically).

``hooks.before_commit()`` runs right before the one call that makes content
visible, so the caller can durably record that dispatch started.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

import httpx

from app.core.config import settings
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_provider import MetaConnector

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_ID_RE = re.compile(r"^[0-9_]{3,128}$")
# Graph error codes (https://developers.facebook.com/docs/graph-api/guides/error-handling).
TOKEN_ERROR_CODES = frozenset({102, 190})
TOKEN_ERROR_SUBCODES = frozenset({458, 459, 460, 463, 464, 467, 492})
TRANSIENT_ERROR_CODES = frozenset({1, 2, 4, 9, 17, 32, 341, 613, 9007, 80001, 80002, 80006})
# Network failures before the request reached Meta are safe to retry; failures
# after it was sent may have created the post.
_SAFE_NETWORK_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


class PublishHooks(Protocol):
    async def before_commit(self) -> None: ...

    async def container_created(self, container_id: str) -> None: ...


class _NoHooks:
    async def before_commit(self) -> None:
        return None

    async def container_created(self, container_id: str) -> None:
        del container_id
        return None


@dataclass(frozen=True)
class PublishMedia:
    kind: str  # image | video
    url: str


@dataclass
class PublishRequest:
    provider: str  # facebook | instagram
    external_id: str
    access_token: str
    post_type: str
    caption: str = ""
    link_url: str | None = None
    media: list[PublishMedia] = field(default_factory=list)
    share_to_feed: bool = True


@dataclass(frozen=True)
class PublishResult:
    remote_post_id: str
    permalink: str | None
    container_id: str | None = None


class GraphPublishError(Exception):
    def __init__(
        self,
        code: str,
        message: str = "",
        *,
        transient: bool = False,
        token_expired: bool = False,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(code)
        self.code = code[:120]
        self.message = " ".join(str(message or "").split())[:500]
        self.transient = transient and not ambiguous and not token_expired
        self.token_expired = token_expired
        self.ambiguous = ambiguous


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_graph_error(
    status_code: int, payload: Any, *, action: str
) -> GraphPublishError:
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return GraphPublishError(
            f"meta-{action}-http-{status_code}",
            "Graph returned an unexpected response",
            transient=status_code >= 500 or status_code == 429,
        )
    code = _int(error.get("code"))
    subcode = _int(error.get("error_subcode"))
    # Only Graph's own message is kept (truncated); it never contains a token.
    message = str(error.get("error_user_msg") or error.get("message") or "")
    label = f"meta-{action}-error-{code if code is not None else 'unknown'}"
    if subcode is not None:
        label += f"-{subcode}"
    if code in TOKEN_ERROR_CODES or subcode in TOKEN_ERROR_SUBCODES:
        return GraphPublishError(label, message, token_expired=True)
    transient = (
        error.get("is_transient") is True
        or code in TRANSIENT_ERROR_CODES
        or status_code == 429
    )
    return GraphPublishError(label, message, transient=transient)


class MetaPublisher:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_seconds: float | None = None,
        max_wait_seconds: float | None = None,
    ) -> None:
        self._transport = transport
        self._connector = MetaConnector(transport=transport)
        self._sleep = sleep
        self._poll_seconds = float(
            poll_seconds if poll_seconds is not None else settings.SOCIAL_IG_CONTAINER_POLL_SECONDS
        )
        self._max_wait = float(
            max_wait_seconds
            if max_wait_seconds is not None
            else settings.SOCIAL_IG_CONTAINER_MAX_WAIT_SECONDS
        )

    # --- HTTP ------------------------------------------------------------------------

    def _secret(self) -> str:
        try:
            _app_id, secret = self._connector._require_credentials()
        except SocialConnectorError as exc:
            raise GraphPublishError("provider-not-configured", "Meta app is not configured") from exc
        return secret

    async def _call(
        self,
        method: str,
        path: str,
        *,
        action: str,
        token: str,
        secret: str,
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        commits: bool = False,
    ) -> dict[str, Any]:
        query = dict(params or {})
        query["appsecret_proof"] = MetaConnector._proof(secret, token)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = await client.request(
                    method, self._connector._graph(path), params=query, data=data, headers=headers
                )
        except _SAFE_NETWORK_ERRORS as exc:
            raise GraphPublishError(
                f"meta-{action}-unreachable", type(exc).__name__, transient=True
            ) from None
        except httpx.HTTPError as exc:
            if commits:
                raise GraphPublishError(
                    "publish-outcome-unknown",
                    f"connection lost after the publish request was sent ({type(exc).__name__})",
                    ambiguous=True,
                ) from None
            raise GraphPublishError(
                f"meta-{action}-network-{type(exc).__name__.lower()}"[:120],
                type(exc).__name__,
                transient=True,
            ) from None
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if response.status_code >= 400 or not isinstance(payload, dict) or "error" in payload:
            graph_error = isinstance(payload, dict) and isinstance(payload.get("error"), dict)
            if commits and not graph_error:
                # No Graph error object: the post may exist. Never replay it blindly.
                raise GraphPublishError(
                    "publish-outcome-unknown",
                    f"unexpected HTTP {response.status_code} response to the publish request",
                    ambiguous=True,
                )
            raise classify_graph_error(response.status_code, payload, action=action)
        return payload

    @staticmethod
    def _id(payload: dict[str, Any], key: str = "id", *, action: str) -> str:
        value = str(payload.get(key) or "")
        if not _ID_RE.fullmatch(value):
            # The request succeeded but no id came back: never claim success.
            raise GraphPublishError(
                f"meta-{action}-no-id", "Graph returned no id", ambiguous=True
            )
        return value

    # --- entry point -----------------------------------------------------------------

    async def publish(
        self, request: PublishRequest, *, hooks: PublishHooks | None = None
    ) -> PublishResult:
        if not _ID_RE.fullmatch(request.external_id or ""):
            raise GraphPublishError("account-id-invalid")
        if not request.access_token:
            raise GraphPublishError("account-reconnect-required", token_expired=True)
        secret = self._secret()
        active_hooks: PublishHooks = hooks or _NoHooks()
        if request.provider == "facebook":
            return await self._facebook(request, secret, active_hooks)
        if request.provider == "instagram":
            return await self._instagram(request, secret, active_hooks)
        raise GraphPublishError("provider-publishing-not-supported")

    # --- Facebook Pages --------------------------------------------------------------

    async def _facebook(
        self, request: PublishRequest, secret: str, hooks: PublishHooks
    ) -> PublishResult:
        page, token = request.external_id, request.access_token
        kind = request.post_type
        if kind in {"text", "link"}:
            data = {"message": request.caption}
            if kind == "link" and request.link_url:
                data["link"] = request.link_url
            await hooks.before_commit()
            payload = await self._call(
                "POST", f"{page}/feed", action="fb-feed", token=token, secret=secret,
                data=data, commits=True,
            )
            post_id = self._id(payload, action="fb-feed")
            return PublishResult(post_id, await self._fb_permalink(post_id, token, secret))
        if kind == "image":
            item = self._single(request, "image")
            await hooks.before_commit()
            payload = await self._call(
                "POST", f"{page}/photos", action="fb-photo", token=token, secret=secret,
                data={"url": item.url, "caption": request.caption, "published": "true"},
                commits=True,
            )
            # /photos returns the photo id and, when published, the feed post id.
            post_id = str(payload.get("post_id") or "")
            if not _ID_RE.fullmatch(post_id):
                post_id = self._id(payload, action="fb-photo")
            return PublishResult(post_id, await self._fb_permalink(post_id, token, secret))
        if kind == "carousel":
            photo_ids: list[str] = []
            for item in request.media:
                if item.kind != "image":
                    raise GraphPublishError("facebook-multi-photo-images-only")
                # Unpublished uploads are invisible until attached; safe to retry.
                payload = await self._call(
                    "POST", f"{page}/photos", action="fb-photo-upload", token=token,
                    secret=secret, data={"url": item.url, "published": "false"},
                )
                photo_ids.append(self._id(payload, action="fb-photo-upload"))
            data = {"message": request.caption}
            for index, photo_id in enumerate(photo_ids):
                data[f"attached_media[{index}]"] = json.dumps({"media_fbid": photo_id})
            await hooks.before_commit()
            payload = await self._call(
                "POST", f"{page}/feed", action="fb-multi-photo", token=token, secret=secret,
                data=data, commits=True,
            )
            post_id = self._id(payload, action="fb-multi-photo")
            return PublishResult(post_id, await self._fb_permalink(post_id, token, secret))
        if kind in {"video", "reel"}:
            item = self._single(request, "video")
            await hooks.before_commit()
            payload = await self._call(
                "POST", f"{page}/videos", action="fb-video", token=token, secret=secret,
                data={"file_url": item.url, "description": request.caption},
                commits=True,
            )
            video_id = self._id(payload, action="fb-video")
            return PublishResult(video_id, await self._fb_permalink(video_id, token, secret))
        raise GraphPublishError("post-type-unsupported")

    async def _fb_permalink(self, object_id: str, token: str, secret: str) -> str | None:
        try:
            payload = await self._call(
                "GET", object_id, action="fb-permalink", token=token, secret=secret,
                params={"fields": "permalink_url"},
            )
        except GraphPublishError:
            return None
        value = str(payload.get("permalink_url") or "")
        if value.startswith("/"):
            value = f"https://www.facebook.com{value}"
        return value[:1024] if value.startswith("https://") else None

    # --- Instagram -------------------------------------------------------------------

    @staticmethod
    def _single(request: PublishRequest, kind: str) -> PublishMedia:
        if len(request.media) != 1 or request.media[0].kind != kind:
            raise GraphPublishError(f"{kind}-post-needs-one-{kind}")
        return request.media[0]

    async def _container(
        self, ig: str, token: str, secret: str, data: dict[str, str], *, action: str
    ) -> str:
        payload = await self._call(
            "POST", f"{ig}/media", action=action, token=token, secret=secret, data=data
        )
        return self._id(payload, action=action)

    async def wait_for_container(self, container_id: str, token: str, secret: str) -> None:
        waited = 0.0
        while True:
            payload = await self._call(
                "GET", container_id, action="ig-container-status", token=token, secret=secret,
                params={"fields": "status_code,status"},
            )
            status = str(payload.get("status_code") or "").upper()
            if status in {"FINISHED", "PUBLISHED"}:
                return
            if status in {"ERROR", "EXPIRED"}:
                raise GraphPublishError(
                    f"instagram-container-{status.lower()}",
                    str(payload.get("status") or "Instagram could not process the media"),
                )
            if waited >= self._max_wait:
                raise GraphPublishError(
                    "instagram-container-timeout",
                    "Instagram is still processing the media",
                    transient=True,
                )
            await self._sleep(self._poll_seconds)
            waited += self._poll_seconds

    async def _instagram(
        self, request: PublishRequest, secret: str, hooks: PublishHooks
    ) -> PublishResult:
        ig, token = request.external_id, request.access_token
        kind = request.post_type
        caption = request.caption
        if kind == "image":
            item = self._single(request, "image")
            container = await self._container(
                ig, token, secret, {"image_url": item.url, "caption": caption},
                action="ig-image-container",
            )
        elif kind in {"video", "reel"}:
            item = self._single(request, "video")
            share = True if kind == "video" else bool(request.share_to_feed)
            container = await self._container(
                ig, token, secret,
                {
                    "media_type": "REELS",
                    "video_url": item.url,
                    "caption": caption,
                    "share_to_feed": "true" if share else "false",
                },
                action="ig-video-container",
            )
        elif kind == "carousel":
            if not 2 <= len(request.media) <= 10:
                raise GraphPublishError("instagram-carousel-needs-2-to-10-items")
            children: list[str] = []
            for item in request.media:
                data = {"is_carousel_item": "true"}
                if item.kind == "video":
                    data.update({"media_type": "VIDEO", "video_url": item.url})
                else:
                    data["image_url"] = item.url
                child = await self._container(ig, token, secret, data, action="ig-carousel-item")
                children.append(child)
            for child in children:
                await self.wait_for_container(child, token, secret)
            container = await self._container(
                ig, token, secret,
                {"media_type": "CAROUSEL", "children": ",".join(children), "caption": caption},
                action="ig-carousel-container",
            )
        else:
            raise GraphPublishError("instagram-requires-media")
        await hooks.container_created(container)
        await self.wait_for_container(container, token, secret)
        await hooks.before_commit()
        payload = await self._call(
            "POST", f"{ig}/media_publish", action="ig-publish", token=token, secret=secret,
            data={"creation_id": container}, commits=True,
        )
        media_id = self._id(payload, action="ig-publish")
        return PublishResult(media_id, await self._ig_permalink(media_id, token, secret), container)

    async def _ig_permalink(self, media_id: str, token: str, secret: str) -> str | None:
        try:
            payload = await self._call(
                "GET", media_id, action="ig-permalink", token=token, secret=secret,
                params={"fields": "permalink"},
            )
        except GraphPublishError:
            return None
        value = str(payload.get("permalink") or "")
        return value[:1024] if value.startswith("https://") else None
