"""Graph API calls of the P3 unified inbox (roadmap 3.6).

Actions: reply to a Facebook Page comment (``/{comment}/comments``) or an
Instagram comment (``/{comment}/replies``), hide or unhide a comment
(``is_hidden`` on Facebook, ``hide`` on Instagram), send a Messenger or
Instagram Direct reply (``/{page}/messages`` with ``messaging_type=RESPONSE``)
and subscribe a Page to the app's webhooks (``/{page}/subscribed_apps``).

Poll fallback: recent Page post comments, recent Instagram media comments and
recent Messenger / Instagram conversations, normalized to ``InboxItem`` like
webhook changes so both paths share one idempotent store.

Every call is pinned to ``META_GRAPH_API_VERSION``, sends the Page token only
in the ``Authorization`` header and carries ``appsecret_proof``. Errors are
``GraphPublishError`` (the publisher's classification: token-expired,
transient, permanent, ambiguous). Nothing here logs a token or message text.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_provider import MetaConnector
from app.services.social_meta_publisher import GraphPublishError, classify_graph_error

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_SAFE_NETWORK_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_ID_RE = re.compile(r"^[0-9_]{3,128}$")
_MID_RE = re.compile(r"^[A-Za-z0-9_:.=+/-]{3,255}$")
PAGE_WEBHOOK_FIELDS = ("feed", "messages")
REPLY_MAX = 2000
POLL_POSTS = 10
POLL_COMMENTS = 25
POLL_CONVERSATIONS = 10
POLL_MESSAGES = 10


@dataclass(frozen=True)
class InboxItem:
    """One normalized Meta comment or message (from a webhook or the poll)."""

    provider: str  # facebook | instagram
    account_external_id: str  # Page id or Instagram Business account id
    channel: str  # comment | dm
    thread_ref: str  # comment:<root comment id> | dm:<participant id>
    message_ref: str
    direction: str  # inbound | outbound
    sent_at: datetime
    action: str = "add"  # add | edited | remove | hide | unhide
    body: str = ""
    parent_ref: str | None = None
    object_ref: str | None = None
    author_ref: str | None = None
    author_name: str | None = None
    participant_ref: str | None = None
    participant_name: str | None = None
    attachments: tuple[dict[str, str], ...] = field(default_factory=tuple)


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def valid_mid(value: Any) -> bool:
    return isinstance(value, str) and bool(_MID_RE.fullmatch(value))


def clean_text(value: Any, *, limit: int = 8000) -> str:
    if not isinstance(value, str):
        return ""
    return value.replace("\x00", "").strip()[:limit]


def clean_name(value: Any) -> str | None:
    text = " ".join(str(value or "").split())[:240]
    return text or None


def parse_time(value: Any, *, fallback: datetime | None = None) -> datetime:
    """Meta times: epoch seconds or milliseconds, or ISO 8601 with ``+0000``."""

    if isinstance(value, bool):
        value = None
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000.0 if value > 10_000_000_000 else float(value)
        try:
            return datetime.fromtimestamp(seconds, UTC)
        except (OverflowError, OSError, ValueError):
            return fallback or datetime.now(UTC)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if re.search(r"[+-]\d{4}$", text):
            text = f"{text[:-2]}:{text[-2:]}"
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return fallback or datetime.now(UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return fallback or datetime.now(UTC)


def attachment_summary(value: Any) -> tuple[dict[str, str], ...]:
    """Keep only an attachment's type and an https URL; never raw payloads."""

    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return ()
    for raw in value[:10]:
        if not isinstance(raw, dict):
            continue
        kind = re.sub(r"[^a-z_]", "", str(raw.get("type") or "file").lower())[:24] or "file"
        payload = as_dict(raw.get("payload"))
        url = payload.get("url")
        entry = {"type": kind}
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 1024:
            entry["url"] = url
        items.append(entry)
    return tuple(items)


class MetaInboxClient:
    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport
        self._connector = MetaConnector(transport=transport)

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
        params: dict[str, str] | None = None,
        data: dict[str, str] | None = None,
        json_body: dict[str, Any] | None = None,
        sends: bool = False,
    ) -> dict[str, Any]:
        if not token:
            raise GraphPublishError("account-reconnect-required", token_expired=True)
        secret = self._secret()
        query = dict(params or {})
        query["appsecret_proof"] = MetaConnector._proof(secret, token)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        content: bytes | None = None
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            content = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = await client.request(
                    method,
                    self._connector._graph(path),
                    params=query,
                    data=data,
                    content=content,
                    headers=headers,
                )
        except _SAFE_NETWORK_ERRORS as exc:
            raise GraphPublishError(
                f"meta-{action}-unreachable", type(exc).__name__, transient=True
            ) from None
        except httpx.HTTPError as exc:
            if sends:
                raise GraphPublishError(
                    "reply-outcome-unknown",
                    f"connection lost after the reply was sent ({type(exc).__name__})",
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
            if sends and not graph_error:
                raise GraphPublishError(
                    "reply-outcome-unknown",
                    f"unexpected HTTP {response.status_code} response to the reply",
                    ambiguous=True,
                )
            raise classify_graph_error(response.status_code, payload, action=action)
        return payload

    # --- actions ---------------------------------------------------------------------

    async def reply_to_comment(
        self, *, provider: str, comment_id: str, token: str, text: str
    ) -> str:
        if not valid_id(comment_id):
            raise GraphPublishError("comment-id-invalid")
        edge = "replies" if provider == "instagram" else "comments"
        payload = await self._call(
            "POST",
            f"{comment_id}/{edge}",
            action="comment-reply",
            token=token,
            data={"message": text},
            sends=True,
        )
        remote = str(payload.get("id") or "")
        if not valid_id(remote):
            raise GraphPublishError("reply-outcome-unknown", "Graph returned no id", ambiguous=True)
        return remote

    async def set_comment_hidden(
        self, *, provider: str, comment_id: str, token: str, hidden: bool
    ) -> bool:
        if not valid_id(comment_id):
            raise GraphPublishError("comment-id-invalid")
        key = "hide" if provider == "instagram" else "is_hidden"
        payload = await self._call(
            "POST",
            comment_id,
            action="comment-hide",
            token=token,
            data={key: "true" if hidden else "false"},
        )
        return payload.get("success") is True or payload.get("id") == comment_id

    async def send_message(
        self, *, page_id: str, token: str, recipient_id: str, text: str
    ) -> str:
        if not valid_id(page_id) or not valid_id(recipient_id):
            raise GraphPublishError("recipient-invalid")
        payload = await self._call(
            "POST",
            f"{page_id}/messages",
            action="message-send",
            token=token,
            json_body={
                "recipient": {"id": recipient_id},
                "messaging_type": "RESPONSE",
                "message": {"text": text},
            },
            sends=True,
        )
        remote = payload.get("message_id")
        if not valid_mid(remote):
            raise GraphPublishError("reply-outcome-unknown", "Graph returned no message id", ambiguous=True)
        return str(remote)

    async def subscribe_page(self, *, page_id: str, token: str) -> bool:
        if not valid_id(page_id):
            raise GraphPublishError("account-id-invalid")
        payload = await self._call(
            "POST",
            f"{page_id}/subscribed_apps",
            action="subscribe",
            token=token,
            data={"subscribed_fields": ",".join(PAGE_WEBHOOK_FIELDS)},
        )
        return payload.get("success") is True

    # --- poll fallback ---------------------------------------------------------------

    async def page_comments(self, *, page_id: str, token: str) -> list[InboxItem]:
        payload = await self._call(
            "GET",
            f"{page_id}/feed",
            action="poll-feed",
            token=token,
            params={
                "fields": (
                    f"id,comments.limit({POLL_COMMENTS}).order(reverse_chronological)"
                    "{id,message,from,created_time,parent{id}}"
                ),
                "limit": str(POLL_POSTS),
            },
        )
        items: list[InboxItem] = []
        for post in _data(payload):
            post_id = str(post.get("id") or "")
            if not valid_id(post_id):
                continue
            for comment in _data(post.get("comments")):
                comment_id = str(comment.get("id") or "")
                if not valid_id(comment_id):
                    continue
                parent = as_dict(comment.get("parent"))
                parent_id = parent.get("id") if valid_id(parent.get("id")) else None
                author = as_dict(comment.get("from"))
                author_id = author.get("id") if valid_id(author.get("id")) else None
                root = parent_id or comment_id
                items.append(
                    InboxItem(
                        provider="facebook",
                        account_external_id=page_id,
                        channel="comment",
                        thread_ref=f"comment:{root}",
                        message_ref=comment_id,
                        parent_ref=parent_id or post_id,
                        object_ref=post_id,
                        direction="outbound" if author_id == page_id else "inbound",
                        sent_at=parse_time(comment.get("created_time")),
                        body=clean_text(comment.get("message")),
                        author_ref=author_id,
                        author_name=clean_name(author.get("name")),
                        participant_ref=None if author_id == page_id else author_id,
                        participant_name=None if author_id == page_id else clean_name(author.get("name")),
                    )
                )
        return items

    async def instagram_comments(self, *, ig_id: str, token: str) -> list[InboxItem]:
        fields = "id,text,username,from,timestamp"
        payload = await self._call(
            "GET",
            f"{ig_id}/media",
            action="poll-media",
            token=token,
            params={
                "fields": f"id,comments.limit({POLL_COMMENTS}){{{fields},replies{{{fields}}}}}",
                "limit": str(POLL_POSTS),
            },
        )
        items: list[InboxItem] = []
        for media in _data(payload):
            media_id = str(media.get("id") or "")
            if not valid_id(media_id):
                continue
            for comment in _data(media.get("comments")):
                if not valid_id(comment.get("id")):
                    continue
                root = comment["id"]
                items.append(_ig_comment(ig_id, media_id, comment, root=root, parent=None))
                for reply in _data(comment.get("replies")):
                    if valid_id(reply.get("id")):
                        items.append(_ig_comment(ig_id, media_id, reply, root=root, parent=root))
        return items

    async def conversations(
        self, *, provider: str, account_external_id: str, page_id: str, token: str
    ) -> list[InboxItem]:
        platform = "instagram" if provider == "instagram" else "messenger"
        payload = await self._call(
            "GET",
            f"{page_id}/conversations",
            action="poll-conversations",
            token=token,
            params={
                "platform": platform,
                "fields": (
                    f"id,participants,messages.limit({POLL_MESSAGES})"
                    "{id,message,from,to,created_time}"
                ),
                "limit": str(POLL_CONVERSATIONS),
            },
        )
        own = {account_external_id, page_id}
        items: list[InboxItem] = []
        for conversation in _data(payload):
            participants = _data(conversation.get("participants"))
            other = next(
                (
                    person
                    for person in participants
                    if valid_id(person.get("id")) and person.get("id") not in own
                ),
                None,
            )
            if other is None:
                continue
            other_id = str(other["id"])
            other_name = clean_name(other.get("name") or other.get("username"))
            for message in _data(conversation.get("messages")):
                mid = message.get("id")
                if not valid_mid(mid):
                    continue
                sender = as_dict(message.get("from"))
                outbound = sender.get("id") in own
                items.append(
                    InboxItem(
                        provider=provider,
                        account_external_id=account_external_id,
                        channel="dm",
                        thread_ref=f"dm:{other_id}",
                        message_ref=str(mid),
                        direction="outbound" if outbound else "inbound",
                        sent_at=parse_time(message.get("created_time")),
                        body=clean_text(message.get("message")),
                        author_ref=str(sender.get("id")) if valid_id(sender.get("id")) else None,
                        author_name=None if outbound else other_name,
                        participant_ref=other_id,
                        participant_name=other_name,
                    )
                )
        return items


def _data(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, dict):
        node = node.get("data")
    if not isinstance(node, list):
        return []
    return [item for item in node if isinstance(item, dict)]


def _ig_comment(
    ig_id: str, media_id: str, comment: dict[str, Any], *, root: str, parent: str | None
) -> InboxItem:
    author = as_dict(comment.get("from"))
    author_id = author.get("id") if valid_id(author.get("id")) else None
    name = clean_name(comment.get("username") or author.get("username"))
    own = author_id == ig_id
    return InboxItem(
        provider="instagram",
        account_external_id=ig_id,
        channel="comment",
        thread_ref=f"comment:{root}",
        message_ref=str(comment["id"]),
        parent_ref=parent or media_id,
        object_ref=media_id,
        direction="outbound" if own else "inbound",
        sent_at=parse_time(comment.get("timestamp")),
        body=clean_text(comment.get("text")),
        author_ref=author_id,
        author_name=name,
        participant_ref=None if own else author_id,
        participant_name=None if own else name,
    )
