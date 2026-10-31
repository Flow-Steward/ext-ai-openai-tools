from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_projected_example_uses_declared_moderation_output_and_is_disabled():
    descriptor = yaml.safe_load((ROOT / "extension-descriptor.yaml").read_text())
    ref = descriptor["artifacts"]["workflows"][0]["ref"]
    example = yaml.safe_load((ROOT / ref).read_text())
    operations = yaml.safe_load(
        (ROOT / "contracts/operation_manifest.yaml").read_text()
    )["operations"]
    operation = next(
        item for item in operations if item["operation_id"] == "moderate_text"
    )
    outputs = {item["name"] for item in operation["outputs"]}
    step = next(item for item in example["steps"] if item["step_id"] == "moderate_text")
    assert example["enabled"] is False
    assert set(step["output_mapping_jsonb"]) <= outputs
    assert step["output_mapping_jsonb"]["flagged"] == "state.moderation_flagged"
    assert not step["connection_binding_jsonb"]


def test_portable_example_is_disabled_and_maps_extension_at_import():
    bundle = yaml.safe_load(
        (ROOT / "artifacts/workflows/demo_openai_moderation.bundle.yaml").read_text()
    )
    assert bundle["schema_version"] == "platform.workflow_bundle.v2"
    assert bundle["kind"] == "workflow_bundle"
    assert bundle["import_hints"]["default_enabled"] is False
    workflow = bundle["workflows"][0]
    assert workflow["execution_graph"]["entry"]["id"] == "moderate_text"
    step = next(
        item for item in workflow["steps"] if item["step_id"] == "moderate_text"
    )
    assert step["connector_id"] == "extension.flowsteward.openai-tools"
    assert "connector_install_id" not in step
    assert not step.get("connection_binding_jsonb")
    assert step["output_mapping_jsonb"] == {"flagged": "state.moderation_flagged"}
