"""Platform constraints for P3 publishing to Facebook Pages and Instagram.

``validate_target`` returns a list of issues for one target account: each is
``{"code", "severity", "field"}`` with severity ``error`` (the target cannot
be published) or ``warning`` (Meta may crop, transcode or reject it). The
same function runs in the composer preview, on schedule/publish and again in
the worker right before the provider call.

Limits follow Meta's published content-publishing constraints; they are kept
here as data so they can be adjusted without touching the publisher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

POST_TYPES = ("text", "link", "image", "carousel", "video", "reel")
PROVIDERS = ("facebook", "instagram")

IG_CAPTION_MAX = 2200
IG_HASHTAGS_MAX = 30
IG_MENTIONS_MAX = 20
IG_IMAGE_MAX_BYTES = 8 * 1024 * 1024
IG_IMAGE_TYPES = frozenset({"image/jpeg"})
IG_IMAGE_MIN_RATIO = 4 / 5
IG_IMAGE_MAX_RATIO = 1.91
IG_IMAGE_MIN_WIDTH = 320
IG_IMAGE_MAX_WIDTH = 1440
IG_CAROUSEL_MIN = 2
IG_CAROUSEL_MAX = 10
IG_VIDEO_TYPES = frozenset({"video/mp4", "video/quicktime"})
IG_VIDEO_MAX_BYTES = 300 * 1024 * 1024
IG_REEL_MIN_MS = 3_000
IG_REEL_MAX_MS = 15 * 60 * 1000
IG_CAROUSEL_VIDEO_MAX_MS = 60_000
IG_REEL_RATIO = 9 / 16

FB_TEXT_MAX = 63_206
FB_IMAGE_MAX_BYTES = 10 * 1024 * 1024
FB_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})
FB_MULTI_PHOTO_MAX = 10
FB_VIDEO_TYPES = frozenset({"video/mp4", "video/quicktime"})
FB_VIDEO_MAX_BYTES = 1024 * 1024 * 1024
FB_VIDEO_MAX_MS = 240 * 60 * 1000

_HASHTAG_RE = re.compile(r"(?<![\w#])#[\w؀-ۿ]+", re.UNICODE)
_MENTION_RE = re.compile(r"(?<![\w@])@[A-Za-z0-9._]{1,30}")


@dataclass(frozen=True)
class MediaInfo:
    ref: str
    kind: str  # image | video
    media_type: str
    size_bytes: int
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None
    filename: str = ""


@dataclass
class TargetContent:
    provider: str
    post_type: str
    caption: str
    link_url: str | None
    media: list[MediaInfo] = field(default_factory=list)
    share_to_feed: bool = True


def issue(code: str, *, severity: str = "error", field_name: str = "post") -> dict[str, str]:
    return {"code": code, "severity": severity, "field": field_name}


def has_errors(issues: list[dict[str, str]]) -> bool:
    return any(item.get("severity") == "error" for item in issues)


def count_hashtags(text: str) -> int:
    return len(_HASHTAG_RE.findall(text or ""))


def count_mentions(text: str) -> int:
    return len(_MENTION_RE.findall(text or ""))


def caption_length(text: str) -> int:
    # Meta counts characters, not bytes; Python ``len`` counts code points.
    return len(text or "")


def valid_link(value: str | None) -> bool:
    if not value or len(value) > 2048:
        return False
    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    return parts.scheme in {"https", "http"} and bool(parts.hostname) and " " not in value


def _ratio(item: MediaInfo) -> float | None:
    if not item.width or not item.height:
        return None
    return item.width / item.height


def _ig_image(item: MediaInfo, index: int, issues: list[dict[str, str]]) -> None:
    where = f"media.{index}"
    if item.media_type not in IG_IMAGE_TYPES:
        issues.append(issue("instagram-image-must-be-jpeg", field_name=where))
    if item.size_bytes > IG_IMAGE_MAX_BYTES:
        issues.append(issue("instagram-image-too-large", field_name=where))
    ratio = _ratio(item)
    if ratio is None:
        issues.append(issue("image-dimensions-unknown", severity="warning", field_name=where))
        return
    # A small tolerance absorbs rounding in exported 4:5 / 1.91:1 images.
    if ratio < IG_IMAGE_MIN_RATIO - 0.005 or ratio > IG_IMAGE_MAX_RATIO + 0.005:
        issues.append(issue("instagram-aspect-ratio-out-of-range", field_name=where))
    if item.width is not None and item.width < IG_IMAGE_MIN_WIDTH:
        issues.append(issue("instagram-image-upscaled", severity="warning", field_name=where))
    if item.width is not None and item.width > IG_IMAGE_MAX_WIDTH:
        issues.append(issue("instagram-image-downscaled", severity="warning", field_name=where))


def _ig_video(
    item: MediaInfo, index: int, issues: list[dict[str, str]], *, max_ms: int, reel: bool
) -> None:
    where = f"media.{index}"
    if item.media_type not in IG_VIDEO_TYPES:
        issues.append(issue("instagram-video-must-be-mp4-or-mov", field_name=where))
    if item.size_bytes > IG_VIDEO_MAX_BYTES:
        issues.append(issue("instagram-video-too-large", field_name=where))
    if item.duration_ms is None:
        issues.append(issue("video-duration-unknown", severity="warning", field_name=where))
    elif item.duration_ms < IG_REEL_MIN_MS:
        issues.append(issue("instagram-video-too-short", field_name=where))
    elif item.duration_ms > max_ms:
        issues.append(issue("instagram-video-too-long", field_name=where))
    ratio = _ratio(item)
    if reel and ratio is not None and abs(ratio - IG_REEL_RATIO) > 0.02:
        issues.append(issue("instagram-reel-not-9-16", severity="warning", field_name=where))


def _instagram(content: TargetContent, issues: list[dict[str, str]]) -> None:
    if caption_length(content.caption) > IG_CAPTION_MAX:
        issues.append(issue("instagram-caption-too-long", field_name="caption"))
    if count_hashtags(content.caption) > IG_HASHTAGS_MAX:
        issues.append(issue("instagram-too-many-hashtags", field_name="caption"))
    if count_mentions(content.caption) > IG_MENTIONS_MAX:
        issues.append(issue("instagram-too-many-mentions", field_name="caption"))
    media = content.media
    kind = content.post_type
    if kind in {"text", "link"}:
        issues.append(issue("instagram-requires-media"))
        return
    if kind == "image":
        if len(media) != 1 or media[0].kind != "image":
            issues.append(issue("image-post-needs-one-image", field_name="media"))
            return
        _ig_image(media[0], 0, issues)
    elif kind == "carousel":
        if not IG_CAROUSEL_MIN <= len(media) <= IG_CAROUSEL_MAX:
            issues.append(issue("instagram-carousel-needs-2-to-10-items", field_name="media"))
        for index, item in enumerate(media):
            if item.kind == "image":
                _ig_image(item, index, issues)
            else:
                _ig_video(item, index, issues, max_ms=IG_CAROUSEL_VIDEO_MAX_MS, reel=False)
    elif kind in {"video", "reel"}:
        if len(media) != 1 or media[0].kind != "video":
            issues.append(issue("video-post-needs-one-video", field_name="media"))
            return
        _ig_video(media[0], 0, issues, max_ms=IG_REEL_MAX_MS, reel=True)
    if content.link_url:
        issues.append(issue("instagram-links-not-clickable", severity="warning", field_name="link_url"))


def _facebook(content: TargetContent, issues: list[dict[str, str]]) -> None:
    if caption_length(content.caption) > FB_TEXT_MAX:
        issues.append(issue("facebook-text-too-long", field_name="caption"))
    media = content.media
    kind = content.post_type
    if kind == "text":
        if not content.caption.strip():
            issues.append(issue("text-post-needs-text", field_name="caption"))
        if media:
            issues.append(issue("text-post-has-media", field_name="media"))
        return
    if kind == "link":
        if not valid_link(content.link_url):
            issues.append(issue("link-invalid", field_name="link_url"))
        if media:
            issues.append(issue("link-post-has-media", field_name="media"))
        return
    if kind in {"image", "carousel"}:
        limit = 1 if kind == "image" else FB_MULTI_PHOTO_MAX
        minimum = 1 if kind == "image" else 2
        if not minimum <= len(media) <= limit:
            issues.append(
                issue(
                    "image-post-needs-one-image"
                    if kind == "image"
                    else "facebook-multi-photo-needs-2-to-10-images",
                    field_name="media",
                )
            )
        for index, item in enumerate(media):
            where = f"media.{index}"
            if item.kind != "image":
                issues.append(issue("facebook-multi-photo-images-only", field_name=where))
                continue
            if item.media_type not in FB_IMAGE_TYPES:
                issues.append(issue("facebook-image-type-unsupported", field_name=where))
            if item.size_bytes > FB_IMAGE_MAX_BYTES:
                issues.append(issue("facebook-image-too-large", field_name=where))
        return
    if kind in {"video", "reel"}:
        if len(media) != 1 or media[0].kind != "video":
            issues.append(issue("video-post-needs-one-video", field_name="media"))
            return
        item = media[0]
        if item.media_type not in FB_VIDEO_TYPES:
            issues.append(issue("facebook-video-type-unsupported", field_name="media.0"))
        if item.size_bytes > FB_VIDEO_MAX_BYTES:
            issues.append(issue("facebook-video-too-large", field_name="media.0"))
        if item.duration_ms is not None and item.duration_ms > FB_VIDEO_MAX_MS:
            issues.append(issue("facebook-video-too-long", field_name="media.0"))
        if kind == "reel":
            # Page Reels use a separate upload API; a reel is posted as a Page video.
            issues.append(issue("facebook-reel-posted-as-video", severity="warning"))


def validate_target(content: TargetContent) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if content.post_type not in POST_TYPES:
        return [issue("post-type-unsupported")]
    if content.provider == "instagram":
        _instagram(content, issues)
    elif content.provider == "facebook":
        _facebook(content, issues)
    else:
        issues.append(issue("provider-publishing-not-supported"))
    return issues


def public_rules() -> dict[str, Any]:
    """Limits the composer mirrors for live warnings (the server stays authoritative)."""

    return {
        "post_types": list(POST_TYPES),
        "instagram": {
            "caption_max": IG_CAPTION_MAX,
            "hashtags_max": IG_HASHTAGS_MAX,
            "mentions_max": IG_MENTIONS_MAX,
            "image_max_bytes": IG_IMAGE_MAX_BYTES,
            "image_types": sorted(IG_IMAGE_TYPES),
            "image_ratio": [round(IG_IMAGE_MIN_RATIO, 4), IG_IMAGE_MAX_RATIO],
            "carousel_items": [IG_CAROUSEL_MIN, IG_CAROUSEL_MAX],
            "video_types": sorted(IG_VIDEO_TYPES),
            "video_max_bytes": IG_VIDEO_MAX_BYTES,
            "reel_duration_ms": [IG_REEL_MIN_MS, IG_REEL_MAX_MS],
        },
        "facebook": {
            "text_max": FB_TEXT_MAX,
            "image_max_bytes": FB_IMAGE_MAX_BYTES,
            "image_types": sorted(FB_IMAGE_TYPES),
            "multi_photo_max": FB_MULTI_PHOTO_MAX,
            "video_types": sorted(FB_VIDEO_TYPES),
            "video_max_bytes": FB_VIDEO_MAX_BYTES,
        },
    }
