from pathlib import Path

import yaml


def test_connection_page_has_required_encrypted_api_key_form():
    root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((root / "ui/ui_manifest.yaml").read_text())
    assert {"ref": "pages/connection.yaml"} in manifest["pages"]
    page = yaml.safe_load((root / "ui/pages/connection.yaml").read_text())
    component = yaml.safe_load(
        (root / "ui/components/connection_form.yaml").read_text()
    )
    assert {"ref": "../components/connection_form.yaml"} in page["components"]
    assert component["type"] == "connection_form"
    assert component["data"]["connection_type"] == "openai_api"
    assert component["data"]["required_secret_fields"] == ["api_key"]
    assert any(
        field["path"] == "api_key" and field["widget"] == "secret" and field["required"]
        for field in component["fields"]
    )
    assert "test_action" not in component["data"]


def test_long_form_workflow_content_uses_textareas():
    root = Path(__file__).resolve().parents[1]
    forms = yaml.safe_load((root / "contracts/step_ui_manifest.yaml").read_text())[
        "forms"
    ]
    long_fields = [
        (form["operation_id"], field)
        for form in forms
        for field in form["fields"]
        if field["name"] in ("prompt", "evidence", "text")
    ]
    assert long_fields
    assert all(
        field["widget_type"] == "textarea" and field.get("help_text")
        for _, field in long_fields
    )
