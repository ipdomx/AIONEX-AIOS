"""Meta Marketing API client for P4 (ad accounts, Insights, campaign objects).

Every call is pinned to ``settings.META_GRAPH_API_VERSION``, sends the token
only in the ``Authorization`` header and adds ``appsecret_proof`` whenever the
token belongs to the platform's Meta app (user OAuth grants). The Owner's
operator token file belongs to the Owner's own app, so it is used without a
proof, exactly like the existing owner-only paths.

Meta's throttling headers (``x-app-usage``, ``x-ad-account-usage``,
``x-business-use-case-usage``, ``x-fb-ads-insights-throttle``) are parsed on
every response and returned to the caller, and throttling error codes raise
``AdsGraphError`` with ``throttled=True`` and a retry hint. No token ever
appears in a URL, an error, a log line or a return value.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, NoReturn

import httpx

from app.core.config import settings
from app.services import ads_metrics as metrics

GRAPH_HOST = "https://graph.facebook.com"
MAX_ACCOUNT_PAGES = 10
MAX_INSIGHT_PAGES = 200
INSIGHT_PAGE_SIZE = 500
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_ID_RE = re.compile(r"^\d{1,32}$")
_REPORT_RE = re.compile(r"^\d{1,40}$")
_PERMISSION_CODES = frozenset({10, 200, 294})
_TRANSIENT_CODES = frozenset({1, 2})

Sleep = Callable[[float], Awaitable[None]]


class AdsGraphError(RuntimeError):
    """Fail-closed Marketing API error with a stable, client-safe code."""

    def __init__(
        self,
        code: str,
        *,
        status_code: int = 502,
        throttled: bool = False,
        transient: bool = False,
        reconnect: bool = False,
        retry_after_seconds: int = 0,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.throttled = throttled
        self.transient = transient
        self.reconnect = reconnect
        self.retry_after_seconds = retry_after_seconds


@dataclass(frozen=True)
class AdsAuth:
    access_token: str = field(repr=False)
    app_secret: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class GraphResult:
    payload: dict[str, Any]
    throttle: metrics.Throttle


@dataclass(frozen=True)
class AdAccount:
    ad_account_id: str
    name: str
    currency: str
    timezone_name: str
    account_status: int
    business_name: str | None

    def public(self) -> dict[str, Any]:
        return {
            "ad_account_id": self.ad_account_id,
            "name": self.name,
            "currency": self.currency,
            "timezone_name": self.timezone_name,
            "account_status": self.account_status,
            "active": self.account_status == 1,
            "business_name": self.business_name,
        }


def numeric_id(value: Any, label: str) -> str:
    text = str(value or "").strip().removeprefix("act_")
    if not _ID_RE.fullmatch(text):
        raise AdsGraphError(f"{label}-invalid", status_code=422)
    return text


def _encode(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _error_code(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:12] or "unknown"


def _account(raw: dict[str, Any]) -> AdAccount | None:
    account_id = str(raw.get("account_id") or str(raw.get("id") or "").removeprefix("act_"))
    if not _ID_RE.fullmatch(account_id):
        return None
    currency = str(raw.get("currency") or "").upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    business = raw.get("business")
    business_name = None
    if isinstance(business, dict):
        business_name = " ".join(str(business.get("name") or "").split())[:240] or None
    try:
        status = int(raw.get("account_status") or 0)
    except (TypeError, ValueError):
        status = 0
    timezone_name = str(raw.get("timezone_name") or "UTC")
    if not re.fullmatch(r"[A-Za-z0-9_+\-/]{1,64}", timezone_name):
        timezone_name = "UTC"
    return AdAccount(
        ad_account_id=account_id,
        name=" ".join(str(raw.get("name") or "").split())[:240] or f"Ad account {account_id}",
        currency=currency,
        timezone_name=timezone_name,
        account_status=status,
        business_name=business_name,
    )


class MetaAdsGraph:
    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._transport = transport
        self._sleep = sleep
        self.calls = 0

    @property
    def api_version(self) -> str:
        version = str(settings.META_GRAPH_API_VERSION or "").strip()
        if not re.fullmatch(r"v\d{1,3}\.\d{1,2}", version):
            raise AdsGraphError("meta-graph-version-invalid", status_code=503)
        return version

    def _url(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self.api_version}/{path.lstrip('/')}"

    @staticmethod
    def _proof(secret: str, token: str) -> str:
        return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()

    async def request(
        self,
        method: str,
        path: str,
        *,
        auth: AdsAuth,
        action: str,
        params: dict[str, Any] | None = None,
        form: dict[str, Any] | None = None,
    ) -> GraphResult:
        query = {key: _encode(value) for key, value in (params or {}).items()}
        if auth.app_secret:
            query["appsecret_proof"] = self._proof(auth.app_secret, auth.access_token)
        headers = {"Accept": "application/json", "Authorization": f"Bearer {auth.access_token}"}
        data = {key: _encode(value) for key, value in form.items()} if form is not None else None
        self.calls += 1
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=_TIMEOUT, follow_redirects=False
            ) as client:
                response = await client.request(
                    method, self._url(path), params=query, data=data, headers=headers
                )
        except httpx.HTTPError as exc:
            raise AdsGraphError(
                f"meta-ads-{action}-unreachable-{type(exc).__name__.lower()}",
                transient=True,
            ) from None
        throttle = metrics.parse_throttle(response.headers)
        try:
            payload = response.json()
        except ValueError:
            payload = None
        error = payload.get("error") if isinstance(payload, dict) else None
        if response.status_code >= 400 or not isinstance(payload, dict) or isinstance(error, dict):
            self._raise(action, response.status_code, error if isinstance(error, dict) else {}, throttle)
        return GraphResult(payload=payload, throttle=throttle)

    @staticmethod
    def _raise(
        action: str, status: int, error: dict[str, Any], throttle: metrics.Throttle
    ) -> NoReturn:
        try:
            code = int(error.get("code") or 0)
        except (TypeError, ValueError):
            code = 0
        label = _error_code(code or status)
        if code in metrics.THROTTLE_ERROR_CODES or status == 429:
            raise AdsGraphError(
                f"meta-ads-{action}-throttled-{label}",
                status_code=429,
                throttled=True,
                transient=True,
                retry_after_seconds=metrics.backoff_seconds(throttle),
            )
        if code == 190 or status == 401:
            raise AdsGraphError(
                f"meta-ads-{action}-token-invalid", status_code=409, reconnect=True
            )
        if code in _PERMISSION_CODES:
            raise AdsGraphError(
                f"meta-ads-{action}-permission-missing-{label}", status_code=403, reconnect=True
            )
        transient = bool(error.get("is_transient")) or code in _TRANSIENT_CODES or status >= 500
        raise AdsGraphError(
            f"meta-ads-{action}-api-error-{label}", status_code=502, transient=transient
        )

    # --- ad accounts -----------------------------------------------------------------

    async def list_ad_accounts(self, auth: AdsAuth) -> list[AdAccount]:
        accounts: list[AdAccount] = []
        seen: set[str] = set()
        after: str | None = None
        for _page in range(MAX_ACCOUNT_PAGES):
            params: dict[str, Any] = {
                "fields": "id,account_id,name,currency,timezone_name,account_status,business{name}",
                "limit": 100,
            }
            if after:
                params["after"] = after
            result = await self.request(
                "GET", "me/adaccounts", auth=auth, action="accounts", params=params
            )
            data = result.payload.get("data")
            if not isinstance(data, list):
                raise AdsGraphError("meta-ads-accounts-response-invalid")
            for raw in data:
                account = _account(raw) if isinstance(raw, dict) else None
                if account is not None and account.ad_account_id not in seen:
                    seen.add(account.ad_account_id)
                    accounts.append(account)
            after = self._next_cursor(result.payload)
            if after is None:
                break
        return accounts

    async def get_ad_account(self, auth: AdsAuth, ad_account_id: str) -> AdAccount:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        result = await self.request(
            "GET",
            f"act_{account_id}",
            auth=auth,
            action="account",
            params={"fields": "id,account_id,name,currency,timezone_name,account_status,business{name}"},
        )
        account = _account(result.payload)
        if account is None or account.ad_account_id != account_id:
            raise AdsGraphError("meta-ads-account-response-invalid")
        return account

    @staticmethod
    def _next_cursor(payload: dict[str, Any]) -> str | None:
        paging = payload.get("paging")
        if not isinstance(paging, dict) or not paging.get("next"):
            return None
        cursors = paging.get("cursors")
        after = cursors.get("after") if isinstance(cursors, dict) else None
        return after if isinstance(after, str) and 0 < len(after) <= 512 else None

    # --- insights --------------------------------------------------------------------

    @staticmethod
    def insight_params(
        *, level: str, date_from: date, date_to: date, breakdown: str
    ) -> dict[str, Any]:
        if level not in metrics.LEVELS:
            raise AdsGraphError("insights-level-invalid", status_code=422)
        params: dict[str, Any] = {
            "level": level,
            "fields": metrics.INSIGHT_FIELDS,
            "time_range": {"since": date_from.isoformat(), "until": date_to.isoformat()},
            "time_increment": 1,
            "limit": INSIGHT_PAGE_SIZE,
        }
        if breakdown != "none":
            keys = metrics.BREAKDOWNS.get(breakdown)
            if keys is None:
                raise AdsGraphError("insights-breakdown-invalid", status_code=422)
            params["breakdowns"] = ",".join(keys)
        return params

    async def _collect(
        self,
        path: str,
        *,
        auth: AdsAuth,
        params: dict[str, Any],
        on_page: Callable[[metrics.Throttle], None] | None = None,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        after: str | None = None
        for _page in range(MAX_INSIGHT_PAGES):
            page_params = dict(params)
            if after:
                page_params["after"] = after
            result = await self.request("GET", path, auth=auth, action="insights", params=page_params)
            if on_page is not None:
                on_page(result.throttle)
            data = result.payload.get("data")
            if not isinstance(data, list):
                raise AdsGraphError("meta-ads-insights-response-invalid")
            rows.extend(item for item in data if isinstance(item, dict))
            after = self._next_cursor(result.payload)
            if after is None:
                return rows
        raise AdsGraphError("meta-ads-insights-too-many-pages")

    async def insights(
        self,
        auth: AdsAuth,
        ad_account_id: str,
        *,
        level: str,
        date_from: date,
        date_to: date,
        breakdown: str = "none",
        on_page: Callable[[metrics.Throttle], None] | None = None,
    ) -> list[dict[str, Any]]:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        params = self.insight_params(
            level=level, date_from=date_from, date_to=date_to, breakdown=breakdown
        )
        return await self._collect(
            f"act_{account_id}/insights", auth=auth, params=params, on_page=on_page
        )

    async def start_report(
        self,
        auth: AdsAuth,
        ad_account_id: str,
        *,
        level: str,
        date_from: date,
        date_to: date,
        breakdown: str = "none",
    ) -> str:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        params = self.insight_params(
            level=level, date_from=date_from, date_to=date_to, breakdown=breakdown
        )
        params.pop("limit", None)
        result = await self.request(
            "POST", f"act_{account_id}/insights", auth=auth, action="report", form=params
        )
        report_id = str(result.payload.get("report_run_id") or "")
        if not _REPORT_RE.fullmatch(report_id):
            raise AdsGraphError("meta-ads-report-response-invalid")
        return report_id

    async def report_status(self, auth: AdsAuth, report_run_id: str) -> tuple[str, int]:
        if not _REPORT_RE.fullmatch(report_run_id or ""):
            raise AdsGraphError("report-run-id-invalid", status_code=422)
        result = await self.request(
            "GET",
            report_run_id,
            auth=auth,
            action="report",
            params={"fields": "async_status,async_percent_completion"},
        )
        status = str(result.payload.get("async_status") or "")
        try:
            percent = int(result.payload.get("async_percent_completion") or 0)
        except (TypeError, ValueError):
            percent = 0
        return status, max(0, min(100, percent))

    async def report_rows(self, auth: AdsAuth, report_run_id: str) -> list[dict[str, Any]]:
        if not _REPORT_RE.fullmatch(report_run_id or ""):
            raise AdsGraphError("report-run-id-invalid", status_code=422)
        return await self._collect(
            f"{report_run_id}/insights", auth=auth, params={"limit": INSIGHT_PAGE_SIZE}
        )

    async def wait_report(
        self, auth: AdsAuth, report_run_id: str, *, attempts: int = 6, interval: float = 5.0
    ) -> bool:
        """Poll a report run a few times; False means "still running, resume later"."""

        for attempt in range(max(1, attempts)):
            status, _percent = await self.report_status(auth, report_run_id)
            if status == "Job Completed":
                return True
            if status in {"Job Failed", "Job Skipped"}:
                raise AdsGraphError("meta-ads-report-failed")
            if attempt + 1 < attempts:
                await self._sleep(interval)
        return False

    # --- campaign objects ------------------------------------------------------------

    async def _create(self, path: str, *, auth: AdsAuth, action: str, form: dict[str, Any]) -> str:
        result = await self.request("POST", path, auth=auth, action=action, form=form)
        object_id = str(result.payload.get("id") or "")
        if not _ID_RE.fullmatch(object_id):
            raise AdsGraphError(f"meta-ads-{action}-response-invalid")
        return object_id

    async def create_campaign(
        self, auth: AdsAuth, ad_account_id: str, *, name: str, objective: str
    ) -> str:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        return await self._create(
            f"act_{account_id}/campaigns",
            auth=auth,
            action="campaign",
            form={
                "name": name,
                "objective": objective,
                "status": "PAUSED",
                "buying_type": "AUCTION",
                "special_ad_categories": [],
                "is_adset_budget_sharing_enabled": False,
            },
        )

    async def create_adset(
        self, auth: AdsAuth, ad_account_id: str, *, form: dict[str, Any]
    ) -> str:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        if str(form.get("status")) != "PAUSED":
            raise AdsGraphError("adset-must-start-paused", status_code=422)
        return await self._create(f"act_{account_id}/adsets", auth=auth, action="adset", form=form)

    async def create_creative(
        self, auth: AdsAuth, ad_account_id: str, *, form: dict[str, Any]
    ) -> str:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        return await self._create(
            f"act_{account_id}/adcreatives", auth=auth, action="creative", form=form
        )

    async def create_ad(
        self, auth: AdsAuth, ad_account_id: str, *, name: str, adset_id: str, creative_id: str
    ) -> str:
        account_id = numeric_id(ad_account_id, "ad-account-id")
        return await self._create(
            f"act_{account_id}/ads",
            auth=auth,
            action="ad",
            form={
                "name": name,
                "adset_id": numeric_id(adset_id, "adset-id"),
                "creative": {"creative_id": numeric_id(creative_id, "creative-id")},
                "status": "PAUSED",
            },
        )

    async def set_status(self, auth: AdsAuth, object_id: str, status: str) -> None:
        if status not in {"ACTIVE", "PAUSED"}:
            raise AdsGraphError("status-not-allowed", status_code=422)
        result = await self.request(
            "POST",
            numeric_id(object_id, "object-id"),
            auth=auth,
            action="status",
            form={"status": status},
        )
        if result.payload.get("success") is not True:
            raise AdsGraphError("meta-ads-status-not-confirmed")
