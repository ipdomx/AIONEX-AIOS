import io
import json
import zipfile

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


def test_video_artifact_contains_editable_production_pipeline():
    files = _department_files(request("video"))
    shots = json.loads(files["production/shot-list.json"])
    assert len(shots) >= 4
    assert "ffmpeg" in files["production/render.sh"]
    assert "00:00:00,000" in files["production/subtitles.srt"]


def test_image_artifact_is_editable_vector_not_fake_binary_media():
    files = _department_files(request("image"))
    assert files["visual.svg"].startswith("<svg")
    assert "prompt pack" in files["prompt-pack.md"].lower()


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
