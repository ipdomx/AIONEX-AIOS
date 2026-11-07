"""Meta Webhooks and signed callbacks for the P3 inbox and App Review (3.6, 3.8).

* ``verify_challenge``: the GET subscription handshake. ``hub.verify_token``
  must equal ``META_WEBHOOK_VERIFY_TOKEN`` (or the private file named by
  ``META_WEBHOOK_VERIFY_TOKEN_FILE``); a missing token fails closed.
* ``verify_signature``: ``X-Hub-Signature-256`` is ``sha256=<hex>`` of the raw
  request body keyed with the app secret, compared in constant time.
* ``parse_payload``: turns the Page ``feed`` and ``messages`` fields and the
  Instagram ``comments`` and ``messages`` fields into ``InboxItem`` changes,
  each with a stable ``event_key`` so a redelivered change is applied once.
* ``parse_signed_request``: the ``signed_request`` of the deauthorize and
  data-deletion callbacks (HMAC-SHA256 over the payload part, app secret).

No token, secret or message text is ever logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.social_connectors import SocialConnectorError
from app.services.social_meta_inbox import (
    InboxItem,
    as_dict,
    attachment_summary,
    clean_name,
    clean_text,
    parse_time,
    valid_id,
    valid_mid,
)
from app.services.social_meta_provider import MetaConnector, _secret_value

MAX_BODY_BYTES = 1024 * 1024
MAX_SIGNED_REQUEST = 8192
# A signed_request older than this, or issued in the future beyond the skew,
# is refused (replay protection for deauthorize / data-deletion callbacks).
SIGNED_REQUEST_MAX_AGE_SECONDS = 24 * 60 * 60
SIGNED_REQUEST_CLOCK_SKEW_SECONDS = 300
FEED_VERBS = {"add": "add", "edited": "edited", "remove": "remove", "hide": "hide", "unhide": "unhide"}


@dataclass(frozen=True)
class WebhookChange:
    object_type: str  # page | instagram
    field: str  # feed | messages | comments
    entry_ref: str
    event_key: str
    item: InboxItem | None  # None: a change the inbox does not store (likes, reads...)


def verify_token_value() -> tuple[str, str | None]:
    return _secret_value(
        settings.META_WEBHOOK_VERIFY_TOKEN,
        settings.META_WEBHOOK_VERIFY_TOKEN_FILE,
        label="META_WEBHOOK_VERIFY_TOKEN",
    )


def webhook_configured() -> bool:
    token, reason = verify_token_value()
    return reason is None and len(token) >= 16


def verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str:
    expected, reason = verify_token_value()
    if reason is not None or len(expected) < 16:
        raise SocialConnectorError("webhook-verify-token-not-configured", status_code=403)
    if mode != "subscribe" or not token or not challenge:
        raise SocialConnectorError("webhook-verify-request-invalid", status_code=403)
    if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        raise SocialConnectorError("webhook-verify-token-mismatch", status_code=403)
    if len(challenge) > 256 or not challenge.isascii() or not challenge.isprintable():
        raise SocialConnectorError("webhook-verify-request-invalid", status_code=403)
    return challenge


def _app_secret() -> str:
    try:
        _app_id, secret = MetaConnector()._require_credentials()
    except SocialConnectorError as exc:
        raise SocialConnectorError("provider-not-configured", status_code=503) from exc
    return secret


def verify_signature(body: bytes, header: str | None) -> None:
    secret = _app_secret()
    value = (header or "").strip()
    if not value.startswith("sha256=") or len(value) != 71:
        raise SocialConnectorError("webhook-signature-missing", status_code=403)
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(value[7:].lower().encode("ascii", "ignore"), expected.encode("ascii")):
        raise SocialConnectorError("webhook-signature-invalid", status_code=403)


def _key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_payload(payload: Any) -> list[WebhookChange]:
    if not isinstance(payload, dict):
        raise SocialConnectorError("webhook-payload-invalid", status_code=400)
    object_type = payload.get("object")
    if object_type not in {"page", "instagram"}:
        return []
    changes: list[WebhookChange] = []
    entries = payload.get("entry")
    if not isinstance(entries, list):
        raise SocialConnectorError("webhook-payload-invalid", status_code=400)
    for entry in entries[:200]:
        if not isinstance(entry, dict) or not valid_id(str(entry.get("id") or "")):
            continue
        entry_id = str(entry["id"])
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            field = str(change.get("field") or "")[:32]
            value = as_dict(change.get("value"))
            key = _key(object_type, entry_id, field, value)
            item: InboxItem | None = None
            if object_type == "page" and field == "feed":
                item = _feed_item(entry_id, value)
            elif object_type == "instagram" and field == "comments":
                item = _instagram_comment_item(entry_id, value)
            changes.append(WebhookChange(object_type, field or "unknown", entry_id, key, item))
        for event in entry.get("messaging") or []:
            if not isinstance(event, dict):
                continue
            key = _key(object_type, entry_id, "messages", event)
            provider = "instagram" if object_type == "instagram" else "facebook"
            item = _messaging_item(provider, entry_id, event)
            changes.append(WebhookChange(object_type, "messages", entry_id, key, item))
    return changes


def _feed_item(page_id: str, value: dict[str, Any]) -> InboxItem | None:
    if value.get("item") != "comment":
        return None
    verb = FEED_VERBS.get(str(value.get("verb") or ""))
    comment_id = str(value.get("comment_id") or "")
    post_id = str(value.get("post_id") or "")
    if verb is None or not valid_id(comment_id):
        return None
    parent_id = str(value.get("parent_id") or "")
    parent = parent_id if valid_id(parent_id) else None
    root = parent if parent and parent != post_id else comment_id
    author = as_dict(value.get("from"))
    author_id = str(author.get("id") or "") if valid_id(str(author.get("id") or "")) else None
    own = author_id == page_id
    name = clean_name(author.get("name"))
    return InboxItem(
        provider="facebook",
        account_external_id=page_id,
        channel="comment",
        thread_ref=f"comment:{root}",
        message_ref=comment_id,
        parent_ref=parent,
        object_ref=post_id if valid_id(post_id) else None,
        direction="outbound" if own else "inbound",
        sent_at=parse_time(value.get("created_time")),
        action=verb,
        body=clean_text(value.get("message")),
        author_ref=author_id,
        author_name=name,
        participant_ref=None if own else author_id,
        participant_name=None if own else name,
    )


def _instagram_comment_item(ig_id: str, value: dict[str, Any]) -> InboxItem | None:
    comment_id = str(value.get("id") or "")
    if not valid_id(comment_id):
        return None
    parent_id = str(value.get("parent_id") or "")
    parent = parent_id if valid_id(parent_id) else None
    media = as_dict(value.get("media"))
    media_id = str(media.get("id") or "")
    author = as_dict(value.get("from"))
    author_id = str(author.get("id") or "") if valid_id(str(author.get("id") or "")) else None
    own = author_id == ig_id
    name = clean_name(author.get("username"))
    return InboxItem(
        provider="instagram",
        account_external_id=ig_id,
        channel="comment",
        thread_ref=f"comment:{parent or comment_id}",
        message_ref=comment_id,
        parent_ref=parent or (media_id if valid_id(media_id) else None),
        object_ref=media_id if valid_id(media_id) else None,
        direction="outbound" if own else "inbound",
        sent_at=parse_time(value.get("timestamp")),
        body=clean_text(value.get("text")),
        author_ref=author_id,
        author_name=name,
        participant_ref=None if own else author_id,
        participant_name=None if own else name,
    )


def _messaging_item(provider: str, entry_id: str, event: dict[str, Any]) -> InboxItem | None:
    message = event.get("message")
    if not isinstance(message, dict):
        return None  # delivery, read, reaction or postback events are not stored
    mid = message.get("mid")
    if not valid_mid(mid):
        return None
    sender = str(as_dict(event.get("sender")).get("id") or "")
    recipient = str(as_dict(event.get("recipient")).get("id") or "")
    echo = message.get("is_echo") is True
    participant = recipient if echo else sender
    if not valid_id(participant) or participant == entry_id:
        return None
    action = "remove" if message.get("is_deleted") is True else "add"
    return InboxItem(
        provider=provider,
        account_external_id=entry_id,
        channel="dm",
        thread_ref=f"dm:{participant}",
        message_ref=str(mid),
        direction="outbound" if echo else "inbound",
        sent_at=parse_time(event.get("timestamp")),
        action=action,
        body=clean_text(message.get("text")),
        author_ref=sender if valid_id(sender) else None,
        participant_ref=participant,
        attachments=attachment_summary(message.get("attachments")),
    )


# --- signed_request (deauthorize and data deletion) -------------------------------------


def _b64decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def parse_signed_request(signed_request: str | None, *, now: int | None = None) -> dict[str, Any]:
    value = (signed_request or "").strip()
    if not value or len(value) > MAX_SIGNED_REQUEST or value.count(".") != 1:
        raise SocialConnectorError("signed-request-invalid", status_code=400)
    encoded_signature, encoded_payload = value.split(".", 1)
    try:
        signature = _b64decode(encoded_signature)
        payload = json.loads(_b64decode(encoded_payload).decode("utf-8"))
    except (ValueError, UnicodeError):
        raise SocialConnectorError("signed-request-invalid", status_code=400) from None
    if not isinstance(payload, dict) or str(payload.get("algorithm") or "").upper() != "HMAC-SHA256":
        raise SocialConnectorError("signed-request-invalid", status_code=400)
    expected = hmac.new(
        _app_secret().encode("utf-8"), encoded_payload.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise SocialConnectorError("signed-request-signature-invalid", status_code=403)
    user_id = str(payload.get("user_id") or "")
    if not valid_id(user_id):
        raise SocialConnectorError("signed-request-user-missing", status_code=400)
    issued_at = payload.get("issued_at")
    current = int(time.time()) if now is None else int(now)
    # FR-23: a captured signed_request never expires on its own, so a replay
    # weeks later would revoke a grant the person made again since. Meta
    # sends these callbacks as the person acts; only a fresh one is honored.
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or issued_at > current + SIGNED_REQUEST_CLOCK_SKEW_SECONDS
        or current - issued_at > SIGNED_REQUEST_MAX_AGE_SECONDS
    ):
        raise SocialConnectorError("signed-request-stale", status_code=400)
    return payload
