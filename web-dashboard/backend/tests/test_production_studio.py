import io
import json
import zipfile

from app.services import production_studio
from app.api.v1.endpoints.studio import (
    DEPARTMENTS,
    StudioRequest,
    _department_files,
    _readme,
    _slug,
)


def request(department: str, **overrides):
    payload = {
        "department": department,
        "title": "AIONEX Live Demo",
        "brief": "Create a complete production-ready demonstration for real user testing.",
        "language": "ar-EG",
        "style": "modern cinematic",
        "target": "mobile and desktop users",
        **overrides,
    }
    return StudioRequest(**payload)


def test_every_requested_department_is_separate_and_available():
    ids = {item["id"] for item in DEPARTMENTS}
    assert ids == {
        "text",
        "website",
        "code",
        "ui-ux",
        "three-d",
        "audio",
        "video",
        "animation",
        "advertising",
        "documentary",
        "image",
        "branding",
    }
    assert len(DEPARTMENTS) == len(ids)


def test_website_artifact_is_immediately_previewable():
    files = _department_files(request("website"))
    assert {"index.html", "styles.css", "app.js"} <= files.keys()
    assert '<meta name="viewport"' in files["index.html"]
    assert 'lang="ar-EG"' in files["index.html"]


def test_threejs_artifact_contains_live_scene_and_asset_contract():
    files = _department_files(request("three-d"))
    assert "scene.js" in files
    assert "three.module.js" in files["scene.js"]
    assert "GLB/GLTF" in files["assets/README.md"]


def test_video_artifact_contains_governed_planned_video_pipeline():
    files = _department_files(request("video"))
    assert {
        "production/video-plan.json",
        "production/continuity-manifest.json",
        "production/shot-list.json",
        "production/provider-prompts.md",
        "production/render.sh",
        "production/subtitles.srt",
    } <= files.keys()
    plan = json.loads(files["production/video-plan.json"])
    continuity = json.loads(files["production/continuity-manifest.json"])
    shots = json.loads(files["production/shot-list.json"])
    assert plan["schema"] == "36F.video-plan.v1"
    assert plan["render_status"] == "planned"
    assert len(plan["scenes"]) == len(shots) == 4
    assert continuity["schema"] == "36F.continuity.v1"
    assert continuity["continuity_id"] == plan["continuity_id"]
    assert continuity["video_plan_checksum"] == plan["checksum"]
    assert continuity["render_status"] == "planned"
    assert [item["scene_id"] for item in shots] == continuity["scene_order"]
    assert all(item["render_status"] == "planned" for item in shots)
    assert "PLANNED ONLY" in files["production/render.sh"]
    assert "ffmpeg" in files["production/render.sh"]
    assert "00:00:00,000" in files["production/subtitles.srt"]
    assert "provider execution has not occurred" in files["production/provider-prompts.md"]


def test_video_archive_remains_provider_neutral_until_durable_video_execution_exists():
    data = request("video")
    artifact = production_studio.build_archive(data, job_id="phase36f-plan-only", revision_number=1)
    assert artifact.manifest["provider_mode"] == "provider_neutral"
    assert artifact.manifest["provider"] is None
    assert artifact.manifest["model"] is None
    assert artifact.manifest["external_requests"] == 0
    assert artifact.manifest["external_cost_usd"] == 0
    with zipfile.ZipFile(io.BytesIO(artifact.content)) as bundle:
        plan = json.loads(bundle.read("production/video-plan.json"))
        continuity = json.loads(bundle.read("production/continuity-manifest.json"))
    assert plan["render_status"] == "planned"
    assert continuity["render_status"] == "planned"


def test_image_artifact_is_governed_design_plan_and_template_not_fake_final_media():
    files = _department_files(request("image"))
    assert files["visual.svg"].startswith("<svg")
    assert 'data-aionex-status="template"' in files["visual.svg"]
    plan = json.loads(files["design-plan.json"])
    assert plan["render_status"] == "planned"
    models = {item["model"] for item in plan["provider_candidates"]}
    assert "gpt-image-2" in models
    assert "gemini-3.1-flash-image" in models
    assert not any("imagen" in item for item in models)
    assert "not a rendered/final asset" in files["prompt-pack.md"]
    exports = json.loads(files["export-presets.json"])
    assert exports["editable"] == "svg"
    assert {"png", "webp", "jpeg"} <= set(exports["raster"])


def test_code_artifact_supports_multiple_language_choices():
    python_files = _department_files(request("code", programming_language="python"))
    typescript_files = _department_files(request("code", programming_language="typescript"))
    assert "src/main.py" in python_files
    assert "tests/test_main.py" in python_files
    assert "src/index.ts" in typescript_files
    assert "package.json" in typescript_files


def test_strategy_departments_produce_distinct_plans():
    outputs = {
        department: _department_files(request(department))["production-plan.md"]
        for department in ("ui-ux", "animation", "advertising", "documentary", "branding")
    }
    assert "Accessibility" in outputs["ui-ux"]
    assert "Storyboard" in outputs["animation"]
    assert "Calls to action" in outputs["advertising"]
    assert "Fact checking" in outputs["documentary"]
    assert "Logo usage" in outputs["branding"]
    assert len(set(outputs.values())) == len(outputs)


def test_package_contract_can_be_downloaded_as_valid_zip():
    data = request("website")
    files = {"README.md": _readme(data), **_department_files(data)}
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path, content in files.items():
            bundle.writestr(path, content)
    archive.seek(0)
    with zipfile.ZipFile(archive) as bundle:
        assert set(bundle.namelist()) >= {"README.md", "index.html", "styles.css", "app.js"}
        assert bundle.testzip() is None


def test_download_filename_slug_is_safe():
    assert _slug("  My 3D / Film Project! ") == "my-3d-film-project"
