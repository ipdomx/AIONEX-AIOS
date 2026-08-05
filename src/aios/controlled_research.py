from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from .cloud_provider_sandbox import ALLOWED_OPENAI_ENDPOINT, OpenAITransportError


DEFAULT_WEB_SEARCH_TOOL_COST_USD = 0.01
DEFAULT_MAXIMUM_INPUT_TOKENS = 16_384
DEFAULT_MAXIMUM_OUTPUT_TOKENS = 3000
DEFAULT_TIMEOUT_SECONDS = 180.0
_URL_PATTERN = re.compile(r"^https://[^\s]+$")


class ControlledResearchError(ValueError):
    """Raised when external research evidence is missing, unsafe, or unverifiable."""


PostJSON = Callable[
    [str, dict[str, Any], Mapping[str, str], float], dict[str, Any]
]


@dataclass(frozen=True, slots=True)
class ResearchSource:
    url: str
    title: str
    domain: str


@dataclass(frozen=True, slots=True)
class ControlledResearchResult:
    provider: str
    model: str
    research_question: str
    summary: str
    verified_facts: tuple[dict[str, Any], ...]
    risks: tuple[str, ...]
    unknowns: tuple[str, ...]
    recommended_constraints: tuple[str, ...]
    sources: tuple[ResearchSource, ...]
    input_tokens: int
    output_tokens: int
    total_tokens: int
    calculated_cost: float
    tool_cost: float
    total_duration: float
    search_calls: int

    def sanitized(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "research_question": self.research_question,
            "summary": self.summary,
            "verified_facts": [dict(item) for item in self.verified_facts],
            "risks": list(self.risks),
            "unknowns": list(self.unknowns),
            "recommended_constraints": list(self.recommended_constraints),
            "sources": [
                {"url": item.url, "title": item.title, "domain": item.domain}
                for item in self.sources
            ],
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "calculated_cost": self.calculated_cost,
            "tool_cost": self.tool_cost,
            "total_duration": self.total_duration,
            "search_calls": self.search_calls,
            "raw_prompt_stored": False,
            "raw_response_stored": False,
            "authorization_header_stored": False,
            "fallback_used": False,
            "production_modified": False,
        }


class ControlledWebResearch:
    """One-call official OpenAI web research with strict source and budget gates."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str,
        input_cost_per_million: float,
        output_cost_per_million: float,
        remaining_budget_usd: float,
        web_search_tool_cost_usd: float = DEFAULT_WEB_SEARCH_TOOL_COST_USD,
        endpoint: str = ALLOWED_OPENAI_ENDPOINT,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        post_json: PostJSON | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        if endpoint != ALLOWED_OPENAI_ENDPOINT:
            raise ValueError("only the official OpenAI Responses endpoint is permitted")
        parts = urlsplit(endpoint)
        if (
            parts.scheme != "https"
            or parts.hostname != "api.openai.com"
            or parts.port not in (None, 443)
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
        ):
            raise ValueError("only the official OpenAI Responses endpoint is permitted")
        if not model:
            raise ValueError("model is required")
        if input_cost_per_million < 0 or output_cost_per_million < 0:
            raise ValueError("model prices must be non-negative")
        if not 0 < web_search_tool_cost_usd <= 0.05:
            raise ValueError("web search tool cost must be between zero and 0.05 USD")
        if not 1 <= timeout_seconds <= DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("timeout must be between 1 and 180 seconds")
        self._api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.input_cost_per_million = float(input_cost_per_million)
        self.output_cost_per_million = float(output_cost_per_million)
        self.remaining_budget_usd = float(remaining_budget_usd)
        self.web_search_tool_cost_usd = float(web_search_tool_cost_usd)
        self.timeout_seconds = float(timeout_seconds)
        self._post_json = post_json or self._default_post_json
        self._lock = threading.Lock()
        self.request_count = 0
        self.search_calls = 0
        worst_case = self.web_search_tool_cost_usd + (
            DEFAULT_MAXIMUM_INPUT_TOKENS * self.input_cost_per_million
            + DEFAULT_MAXIMUM_OUTPUT_TOKENS * self.output_cost_per_million
        ) / 1_000_000
        if worst_case > self.remaining_budget_usd + 1e-12:
            raise ControlledResearchError(
                "one worst-case web research request exceeds the remaining budget"
            )

    def __repr__(self) -> str:
        return (
            "ControlledWebResearch(api_key='[REDACTED]', "
            f"model={self.model!r}, endpoint={self.endpoint!r})"
        )

    def execute(self, *, project: str, objective: str) -> ControlledResearchResult:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._execute_async(project=project, objective=objective))
        raise RuntimeError("ControlledWebResearch.execute cannot run inside an event loop")

    async def _execute_async(
        self, *, project: str, objective: str
    ) -> ControlledResearchResult:
        selected_project = project.strip()
        selected_objective = objective.strip()
        if len(selected_project) < 2 or len(selected_objective) < 10:
            raise ControlledResearchError("project and objective are required")
        if self.request_count:
            raise ControlledResearchError("controlled web research can run only once")
        self.request_count = 1
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._system_prompt(),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self._prompt(selected_project, selected_objective),
                        }
                    ],
                },
            ],
            "tools": [
                {
                    "type": "web_search",
                    "search_context_size": "low",
                }
            ],
            "include": ["web_search_call.action.sources"],
            "tool_choice": "required",
            "max_tool_calls": 1,
            "max_output_tokens": DEFAULT_MAXIMUM_OUTPUT_TOKENS,
            "store": False,
            "reasoning": {"effort": "none"},
            "text": {
                "verbosity": "low",
                "format": {
                    "type": "json_schema",
                    "name": "aionex_controlled_research",
                    "strict": True,
                    "schema": self._schema(),
                }
            },
        }
        started = time.monotonic()
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                self._post_serialized,
                self.endpoint,
                payload,
                self._headers(),
                self.timeout_seconds,
            ),
            timeout=self.timeout_seconds + 2.0,
        )
        duration = time.monotonic() - started
        if not isinstance(raw, dict) or raw.get("status") != "completed":
            reason = ""
            if isinstance(raw, Mapping):
                incomplete = raw.get("incomplete_details")
                if isinstance(incomplete, Mapping):
                    reason = str(incomplete.get("reason") or "")[:80]
            raise OpenAITransportError(
                "OpenAI web research response was not completed"
                + (f": {reason}" if reason else ""),
                error_type="response_status",
                error_code="response_incomplete",
                error_param=reason,
            )
        text = self._extract_output_text(raw)
        sources, search_calls = self._extract_sources(raw)
        self.search_calls = search_calls
        if search_calls != 1:
            raise ControlledResearchError(
                "controlled research requires exactly one completed web search call"
            )
        if len(sources) < 2 or len({source.domain for source in sources}) < 2:
            raise ControlledResearchError(
                "controlled research requires at least two independent web sources"
            )
        result = self._validate_result(text, sources)
        usage = raw.get("usage") or {}
        if not isinstance(usage, Mapping):
            raise OpenAITransportError("OpenAI web research usage was invalid")
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)
        total_tokens = int(
            usage.get("total_tokens", input_tokens + output_tokens) or 0
        )
        token_cost = (
            input_tokens * self.input_cost_per_million
            + output_tokens * self.output_cost_per_million
        ) / 1_000_000
        calculated_cost = token_cost + self.web_search_tool_cost_usd
        if calculated_cost > self.remaining_budget_usd + 1e-12:
            raise ControlledResearchError(
                "web research response exceeded the remaining budget"
            )
        return ControlledResearchResult(
            provider="openai",
            model=self.model,
            research_question=str(result["research_question"]),
            summary=str(result["summary"]),
            verified_facts=tuple(dict(item) for item in result["verified_facts"]),
            risks=tuple(str(item) for item in result["risks"]),
            unknowns=tuple(str(item) for item in result["unknowns"]),
            recommended_constraints=tuple(
                str(item) for item in result["recommended_constraints"]
            ),
            sources=tuple(sources),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            calculated_cost=round(calculated_cost, 10),
            tool_cost=self.web_search_tool_cost_usd,
            total_duration=round(duration, 6),
            search_calls=search_calls,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _post_serialized(
        self,
        url: str,
        payload: dict[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        with self._lock:
            return self._post_json(url, payload, headers, timeout_seconds)

    @classmethod
    def _default_post_json(
        cls,
        url: str,
        payload: dict[str, Any],
        headers: Mapping[str, str],
        timeout_seconds: float,
    ) -> dict[str, Any]:
        if url != ALLOWED_OPENAI_ENDPOINT:
            raise ValueError("only the official OpenAI Responses endpoint is permitted")
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=dict(headers),
            method="POST",
        )
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_code = ""
            error_type = ""
            error_param = ""
            try:
                decoded = json.loads(
                    exc.read().decode("utf-8", errors="replace")
                )
                error = decoded.get("error") if isinstance(decoded, Mapping) else None
                if isinstance(error, Mapping):
                    error_code = str(error.get("code", ""))[:80]
                    error_type = str(error.get("type", ""))[:80]
                    error_param = str(error.get("param", ""))[:80]
            except (json.JSONDecodeError, AttributeError, TypeError):
                pass
            safe_detail = "/".join(
                part
                for part in (
                    error_type,
                    error_code,
                    f"param={error_param}" if error_param else "",
                )
                if part
            )
            raise OpenAITransportError(
                f"OpenAI HTTP {exc.code}{': ' + safe_detail if safe_detail else ''}",
                status_code=exc.code,
                error_code=error_code,
            ) from None
        except (URLError, TimeoutError, OSError) as exc:
            raise OpenAITransportError(
                f"OpenAI web research connection failed: {type(exc).__name__}"
            ) from None
        try:
            decoded = json.loads(body)
        except json.JSONDecodeError:
            raise OpenAITransportError("OpenAI web research returned invalid JSON") from None
        if not isinstance(decoded, dict):
            raise OpenAITransportError(
                "OpenAI web research returned a non-object response"
            )
        return decoded

    @staticmethod
    def _extract_output_text(raw: Mapping[str, Any]) -> str:
        direct = raw.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        pieces: list[str] = []
        output = raw.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, Mapping) or item.get("type") != "message":
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if (
                        isinstance(part, Mapping)
                        and part.get("type") == "output_text"
                        and isinstance(part.get("text"), str)
                    ):
                        pieces.append(str(part["text"]))
        text = "".join(pieces)
        if not text.strip():
            raise OpenAITransportError(
                "OpenAI web research response did not contain output text"
            )
        return text

    @classmethod
    def _extract_sources(
        cls, raw: Mapping[str, Any]
    ) -> tuple[list[ResearchSource], int]:
        found: dict[str, ResearchSource] = {}
        search_calls = 0
        output = raw.get("output")
        if not isinstance(output, list):
            return [], 0
        for item in output:
            if not isinstance(item, Mapping):
                continue
            if item.get("type") == "web_search_call":
                search_calls += 1
                action = item.get("action")
                if isinstance(action, Mapping):
                    candidates = action.get("sources")
                    if isinstance(candidates, list):
                        for candidate in candidates:
                            if isinstance(candidate, Mapping):
                                cls._add_source(
                                    found,
                                    candidate.get("url"),
                                    candidate.get("title"),
                                )
                    cls._add_source(
                        found, action.get("url"), action.get("title")
                    )
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                annotations = part.get("annotations")
                if not isinstance(annotations, list):
                    continue
                for annotation in annotations:
                    if not isinstance(annotation, Mapping):
                        continue
                    nested = annotation.get("url_citation")
                    source = nested if isinstance(nested, Mapping) else annotation
                    if source.get("type") not in {None, "url_citation"}:
                        continue
                    cls._add_source(
                        found, source.get("url"), source.get("title")
                    )
        return sorted(found.values(), key=lambda item: item.url), search_calls

    @staticmethod
    def _add_source(
        found: dict[str, ResearchSource], url_value: Any, title_value: Any
    ) -> None:
        url = str(url_value or "").strip()
        if not _URL_PATTERN.fullmatch(url):
            return
        parts = urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.username is not None
            or parts.password is not None
        ):
            return
        normalized = parts._replace(fragment="").geturl()
        found.setdefault(
            normalized,
            ResearchSource(
                url=normalized,
                title=str(title_value or parts.hostname)[:240],
                domain=parts.hostname.lower(),
            ),
        )

    @classmethod
    def _validate_result(
        cls, text: str, sources: list[ResearchSource]
    ) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ControlledResearchError(
                "web research synthesis was not valid JSON"
            ) from exc
        expected = {
            "schema_version",
            "research_question",
            "summary",
            "verified_facts",
            "risks",
            "unknowns",
            "recommended_constraints",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ControlledResearchError("web research synthesis keys are invalid")
        if payload.get("schema_version") != 1:
            raise ControlledResearchError("web research schema version is invalid")
        cls._validate_text(payload["research_question"], "research_question", 10, 500)
        cls._validate_text(payload["summary"], "summary", 20, 1800)
        source_urls = {source.url for source in sources}
        facts = payload["verified_facts"]
        if not isinstance(facts, list) or not 2 <= len(facts) <= 10:
            raise ControlledResearchError(
                "web research requires two to ten verified facts"
            )
        used_domains: set[str] = set()
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict) or set(fact) != {
                "claim",
                "source_urls",
                "confidence",
            }:
                raise ControlledResearchError("verified fact schema is invalid")
            cls._validate_text(fact["claim"], f"fact[{index}].claim", 10, 600)
            urls = fact["source_urls"]
            if not isinstance(urls, list) or not urls:
                raise ControlledResearchError("every verified fact requires a source")
            if any(str(url) not in source_urls for url in urls):
                raise ControlledResearchError(
                    "verified fact references an unobserved source URL"
                )
            for url in urls:
                hostname = urlsplit(str(url)).hostname
                if hostname:
                    used_domains.add(hostname.lower())
            confidence = float(fact["confidence"])
            if not 0.0 <= confidence <= 1.0:
                raise ControlledResearchError("fact confidence is outside zero to one")
        if len(used_domains) < 2:
            raise ControlledResearchError(
                "verified facts must rely on at least two independent domains"
            )
        for name, minimum, maximum in (
            ("risks", 1, 8),
            ("unknowns", 1, 8),
            ("recommended_constraints", 1, 10),
        ):
            values = payload[name]
            if not isinstance(values, list) or not minimum <= len(values) <= maximum:
                raise ControlledResearchError(f"{name} cardinality is invalid")
            for index, value in enumerate(values):
                cls._validate_text(value, f"{name}[{index}]", 3, 500)
        return payload

    @staticmethod
    def _validate_text(value: Any, name: str, minimum: int, maximum: int) -> None:
        if not isinstance(value, str) or not minimum <= len(value.strip()) <= maximum:
            raise ControlledResearchError(f"{name} text is invalid")

    @staticmethod
    def _schema() -> dict[str, Any]:
        fact = {
            "type": "object",
            "additionalProperties": False,
            "required": ["claim", "source_urls", "confidence"],
            "properties": {
                "claim": {"type": "string"},
                "source_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "confidence": {"type": "number"},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "schema_version",
                "research_question",
                "summary",
                "verified_facts",
                "risks",
                "unknowns",
                "recommended_constraints",
            ],
            "properties": {
                "schema_version": {"type": "integer", "enum": [1]},
                "research_question": {"type": "string"},
                "summary": {"type": "string"},
                "verified_facts": {"type": "array", "items": fact},
                "risks": {"type": "array", "items": {"type": "string"}},
                "unknowns": {"type": "array", "items": {"type": "string"}},
                "recommended_constraints": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are the independent research and fact-verification office of AIONEX AIOS. "
            "Use the web search tool exactly once. Prefer primary and authoritative sources. "
            "Cross-check material claims across at least two independent domains. Distinguish "
            "verified facts from unknowns. Return only the strict JSON object. Include only "
            "HTTPS source URLs actually used by web search. Do not include credentials, code, "
            "personal data, raw search snippets, or unsupported claims."
        )

    @staticmethod
    def _prompt(project: str, objective: str) -> str:
        return (
            f"Project: {project}\nObjective: {objective}\n\n"
            "Research the current external facts, standards, constraints, user expectations, "
            "regulatory or technical assumptions that materially affect correct implementation. "
            "Keep the scope proportionate to the objective. Produce actionable constraints for "
            "the engineering departments and identify anything that still requires owner input."
        )
