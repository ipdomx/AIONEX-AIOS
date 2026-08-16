from __future__ import annotations

import pytest

from aios.project_archetypes import infer_application_type
from aios.universal_project_builder import infer_project_profile


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        ("Build a SaaS website and REST API", {"web", "api", "cli"}),
        ("Build Android and iOS mobile app", {"mobile", "api", "cli"}),
        ("Build a Windows desktop application", {"desktop", "web", "cli"}),
        ("Build a Chrome browser extension", {"browser_extension", "cli"}),
        ("Build Telegram bot and WhatsApp bot", {"bot", "api", "cli"}),
        ("Build AI RAG agent", {"ai", "api", "cli"}),
        (
            "Build member accounts with login and password authentication",
            {"auth", "api", "cli"},
        ),
        ("Build analytics ETL data pipeline", {"data", "cli"}),
        ("Build ecommerce store with subscriptions", {"commerce", "web", "api", "cli"}),
        ("Build a 2D game", {"game", "web", "cli"}),
        ("Build a 3D WebGL viewer", {"three_d", "web", "cli"}),
        ("Build IoT firmware for a sensor", {"iot", "cli"}),
        ("Build command line automation", {"cli"}),
        ("Build a PostgreSQL database and migrations", {"database", "api", "cli"}),
        ("Build Terraform Kubernetes cloud infrastructure", {"infrastructure", "cli"}),
        (
            "Build a Solidity smart contract for blockchain",
            {"smart_contract", "web", "cli"},
        ),
        ("Build a serverless Lambda function", {"serverless", "api", "cli"}),
        ("Build a software SDK library", {"library", "cli"}),
        ("Build a WebXR virtual reality app", {"xr", "web", "cli"}),
        ("Build robotics ROS2 simulator for a drone", {"robotics", "cli"}),
        (
            "Build a video production storyboard and graphic design package",
            {"media", "cli"},
        ),
        ("فكرة جديدة غير مصنفة لكن قابلة للتنفيذ", {"web", "api", "cli"}),
    ],
)
def test_every_project_family_routes_to_a_buildable_capability_profile(
    objective: str, expected: set[str]
) -> None:
    profile = infer_project_profile(objective)
    assert expected.issubset(set(profile.targets))
    assert "governed-build" in profile.capabilities
    assert infer_application_type(objective, "web_application") in {
        "universal_application",
        "realtime_communications",
    }


def test_realtime_keeps_dedicated_hardened_builder() -> None:
    assert (
        infer_application_type(
            "تطبيق مكالمات صوت وفيديو بين الأعضاء", "web_application"
        )
        == "realtime_communications"
    )


def test_media_production_is_not_misclassified_as_realtime_calling() -> None:
    assert (
        infer_application_type(
            "Build a video production and editing project", "web_application"
        )
        == "universal_application"
    )
    assert (
        infer_application_type(
            "Build a private video call application", "web_application"
        )
        == "realtime_communications"
    )
