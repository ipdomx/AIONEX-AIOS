from __future__ import annotations

import asyncio
import json

import pytest

from aios.controlled_research import (
    ControlledResearchError,
    ControlledWebResearch,
)


API_KEY = "unit-test-provider-key-not-a-real-credential"
MODEL = "gpt-5-mini"
SOURCE_ONE = "https://example.org/standards/current"
SOURCE_TWO = "https://docs.example.net/guidance/latest"


def _synthesis() -> dict:
    return {
        "schema_version": 1,
        "research_question": "Which current constraints affect the requested project?",
        "summary": (
            "The current evidence supports a controlled implementation with explicit "
            "privacy, interoperability and release constraints."
        ),
        "verified_facts": [
            {
                "claim": "The primary standard requires an explicit evidence record.",
                "source_urls": [SOURCE_ONE],
                "confidence": 0.94,
            },
            {
                "claim": "The implementation guidance requires a documented review gate.",
                "source_urls": [SOURCE_TWO],
                "confidence": 0.91,
            },
        ],
        "risks": ["A current external dependency may change after the research date."],
        "unknowns": ["The owner has not selected a final deployment jurisdiction."],
        "recommended_constraints": [
            "Retain source URLs and repeat research before production release."
        ],
    }


def _response(*, sources: bool = True, search_calls: int = 1) -> dict:
    output = []
    for index in range(search_calls):
        output.append(
            {
                "id": f"ws_{index}",
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": ["current implementation constraints"],
                    "sources": (
                        [
                            {
                                "type": "url",
                                "url": SOURCE_ONE,
                                "title": "Current standard",
                            },
                            {
                                "type": "url",
                                "url": SOURCE_TWO,
                                "title": "Implementation guidance",
                            },
                        ]
                        if sources
                        else []
                    ),
                },
            }
        )
    output.append(
        {
            "id": "msg_1",
            "type": "message",
            "status": "completed",
            "content": [
                {
                    "type": "output_text",
                    "text": json.dumps(_synthesis()),
                    "annotations": (
                        [
                            {
                                "type": "url_citation",
                                "url": SOURCE_ONE,
                                "title": "Current standard",
                            },
                            {
                                "type": "url_citation",
                                "url": SOURCE_TWO,
                                "title": "Implementation guidance",
                            },
                        ]
                        if sources
                        else []
                    ),
                }
            ],
        }
    )
    return {
        "id": "resp_research",
        "status": "completed",
        "model": MODEL,
        "output": output,
        "usage": {
            "input_tokens": 600,
            "output_tokens": 400,
            "total_tokens": 1000,
        },
    }


def test_controlled_research_uses_one_official_search_and_returns_sources() -> None:
    captured = {}

    def post_json(url, payload, headers, timeout):
        captured.update(
            {
                "url": url,
                "payload": payload,
                "headers": dict(headers),
                "timeout": timeout,
            }
        )
        return _response()

    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=post_json,
    )
    result = executor.execute(
        project="AIONEX Demo",
        objective="Build a current evidence-based governed project prototype.",
    )

    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["payload"]["tools"] == [
        {"type": "web_search", "search_context_size": "low"}
    ]
    assert captured["payload"]["include"] == [
        "web_search_call.action.sources"
    ]
    assert captured["payload"]["max_tool_calls"] == 1
    assert captured["payload"]["tool_choice"] == "required"
    assert captured["payload"]["store"] is False
    assert captured["payload"]["reasoning"] == {"effort": "none"}
    assert captured["payload"]["text"]["verbosity"] == "low"
    assert "temperature" not in captured["payload"]
    assert captured["payload"]["text"]["format"]["strict"] is True
    assert captured["headers"]["Authorization"] == f"Bearer {API_KEY}"
    assert result.search_calls == 1
    assert len(result.sources) == 2
    assert {source.domain for source in result.sources} == {
        "example.org",
        "docs.example.net",
    }
    assert result.calculated_cost == pytest.approx(0.01095)
    sanitized = result.sanitized()
    assert sanitized["raw_response_stored"] is False
    assert sanitized["fallback_used"] is False
    assert API_KEY not in json.dumps(sanitized)
    assert API_KEY not in repr(executor)


def test_controlled_research_rejects_missing_independent_sources() -> None:
    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: _response(sources=False),
    )
    with pytest.raises(ControlledResearchError, match="independent web sources"):
        executor.execute(
            project="AIONEX Demo",
            objective="Build a current evidence-based governed project prototype.",
        )


def test_controlled_research_rejects_more_than_one_search_call() -> None:
    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: _response(search_calls=2),
    )
    with pytest.raises(ControlledResearchError, match="exactly one"):
        executor.execute(
            project="AIONEX Demo",
            objective="Build a current evidence-based governed project prototype.",
        )


def test_controlled_research_fails_closed_before_request_when_budget_is_small() -> None:
    calls = 0

    def post_json(*args):
        nonlocal calls
        calls += 1
        return _response()

    with pytest.raises(ControlledResearchError, match="remaining budget"):
        ControlledWebResearch(
            API_KEY,
            model=MODEL,
            input_cost_per_million=0.25,
            output_cost_per_million=2.0,
            remaining_budget_usd=0.01,
            web_search_tool_cost_usd=0.01,
            post_json=post_json,
        )
    assert calls == 0


def test_controlled_research_can_run_only_once() -> None:
    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: _response(),
    )
    executor.execute(
        project="AIONEX Demo",
        objective="Build a current evidence-based governed project prototype.",
    )
    with pytest.raises(ControlledResearchError, match="only once"):
        executor.execute(
            project="AIONEX Demo",
            objective="Build a current evidence-based governed project prototype.",
        )


def test_execute_rejects_running_event_loop() -> None:
    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: _response(),
    )

    async def run() -> None:
        with pytest.raises(RuntimeError, match="event loop"):
            executor.execute(
                project="AIONEX Demo",
                objective="Build a current evidence-based governed project prototype.",
            )

    asyncio.run(run())


def test_incomplete_research_response_has_sanitized_diagnostics() -> None:
    response = _response()
    response["status"] = "incomplete"
    response["incomplete_details"] = {"reason": "max_output_tokens"}
    executor = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: response,
    )
    from aios.cloud_provider_sandbox import OpenAITransportError

    with pytest.raises(OpenAITransportError) as raised:
        executor.execute(
            project="AIONEX Demo",
            objective="Build a current evidence-based governed project prototype.",
        )
    assert raised.value.error_type == "response_status"
    assert raised.value.error_code == "response_incomplete"
    assert raised.value.error_param == "max_output_tokens"
    assert API_KEY not in str(raised.value)


def test_verified_fact_urls_are_canonicalized_to_observed_sources() -> None:
    response = _response()
    synthesis = _synthesis()
    synthesis["verified_facts"][0]["source_urls"] = [
        SOURCE_ONE + "/?utm_source=search#section"
    ]
    response["output"][-1]["content"][0]["text"] = json.dumps(synthesis)
    result = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: response,
    ).execute(
        project="AIONEX Demo",
        objective="Build a current evidence-based governed project prototype.",
    )
    assert result.verified_facts[0]["source_urls"] == [SOURCE_ONE]


def test_optional_research_lists_are_bounded_without_fabrication() -> None:
    response = _response()
    synthesis = _synthesis()
    synthesis["risks"] = []
    synthesis["unknowns"] = []
    synthesis["recommended_constraints"] = [
        f"Constraint {index}: retain a deterministic local verification path."
        for index in range(14)
    ]
    response["output"][-1]["content"][0]["text"] = json.dumps(synthesis)
    result = ControlledWebResearch(
        API_KEY,
        model=MODEL,
        input_cost_per_million=0.25,
        output_cost_per_million=2.0,
        remaining_budget_usd=0.05,
        web_search_tool_cost_usd=0.01,
        post_json=lambda *args: response,
    ).execute(
        project="AIONEX Demo",
        objective="Build a current evidence-based governed project prototype.",
    )
    assert result.risks == ()
    assert result.unknowns == ()
    assert len(result.recommended_constraints) == 10
    assert result.recommended_constraints[0].startswith("Constraint 0:")
