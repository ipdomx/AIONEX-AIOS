from app.services.security_api_analyzer import analyze_openapi


def test_mutating_unsecured_operation_is_flagged():
    spec = {"openapi": "3.1.0", "paths": {"/projects/{project_id}": {"delete": {"parameters": [{"name": "project_id", "in": "path"}], "responses": {"200": {}}}}}, "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}}
    result = analyze_openapi(spec)
    titles = {item["title"] for item in result["findings"]}
    assert "Mutating API operation has no declared security requirement" in titles


def test_secured_operation_does_not_trigger_missing_security():
    spec = {"openapi": "3.1.0", "security": [{"bearer": []}], "paths": {"/projects": {"post": {"responses": {"201": {}, "403": {}}}}}, "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}}}
    result = analyze_openapi(spec)
    assert not [item for item in result["findings"] if item["title"] == "Mutating API operation has no declared security requirement"]
