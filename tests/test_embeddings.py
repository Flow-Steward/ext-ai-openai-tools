import json
import math
import socket
from copy import deepcopy
from unittest.mock import patch

import pytest
import provider


MODEL_SMALL = "text-embedding-3-small"
MODEL_LARGE = "text-embedding-3-large"


def response(count=1, dimensions=3, model=MODEL_SMALL):
    return {
        "model": model,
        "data": [
            {"index": index, "embedding": [float(index + 1)] * dimensions}
            for index in range(count)
        ],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }


def test_default_model_and_dimensions_and_text_are_sent_once():
    payload = response(dimensions=1536)
    with patch.object(
        provider, "request_json", return_value=(payload, "req_1")
    ) as send:
        result = provider.perform("embed", {"texts": ["  café  "]}, "secret", {})
    send.assert_called_once_with(
        "/embeddings",
        {"model": MODEL_SMALL, "input": ["  café  "], "encoding_format": "float"},
        "secret",
    )
    assert result == {
        "vectors": [[1.0] * 1536],
        "model": MODEL_SMALL,
        "dimensions": 1536,
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
        "request_id": "req_1",
    }
    assert "café" not in json.dumps(result)
    assert "secret" not in json.dumps(result)


def test_batch_results_reordered_by_index_and_custom_dimensions():
    payload = response(count=2, model=MODEL_LARGE)
    payload["data"].reverse()
    with patch.object(
        provider, "request_json", return_value=(payload, "req_2")
    ) as send:
        result = provider.perform(
            "embed",
            {"texts": ["first", "second"], "model": MODEL_LARGE, "dimensions": 3},
            "secret",
            {},
        )
    assert send.call_args.args[1] == {
        "model": MODEL_LARGE,
        "input": ["first", "second"],
        "dimensions": 3,
        "encoding_format": "float",
    }
    assert result["vectors"] == [[1.0] * 3, [2.0] * 3]
    assert result["model"] == MODEL_LARGE
    assert result["dimensions"] == 3


@pytest.mark.parametrize(
    "args",
    [
        {},
        {"texts": []},
        {"texts": "text"},
        {"texts": [""]},
        {"texts": ["  "]},
        {"texts": [1]},
        {"texts": ["\ud800"]},
        {"texts": ["x"] * 5},
        {"texts": ["é" * 4001]},
        {"texts": ["x"], "model": "unknown"},
        {"texts": ["x"], "model": None},
        {"texts": ["x"], "dimensions": None},
        {"texts": ["x"], "dimensions": True},
        {"texts": ["x"], "dimensions": 0},
        {"texts": ["x"], "dimensions": 1.5},
        {"texts": ["x"], "dimensions": 1.0},
        {"texts": ["x"], "dimensions": "3"},
        {"texts": ["x"], "dimensions": 1537},
        {"texts": ["x"], "model": MODEL_LARGE, "dimensions": 3073},
    ],
)
def test_invalid_input_rejected_before_any_provider_request(args):
    with patch.object(provider, "request_json") as send:
        with pytest.raises(provider.ProviderError) as error:
            provider.perform("embed", args, "secret", {})
    assert error.value.code == "invalid_payload"
    send.assert_not_called()


def malformed_responses():
    valid = response(count=2)
    changes = []
    for mutation in (
        lambda p: p.update(model="other"),
        lambda p: p.update(data={}),
        lambda p: p["data"].__setitem__(0, "invalid"),
        lambda p: p["data"].pop(),
        lambda p: p["data"][1].update(index=0),
        lambda p: p["data"][1].update(index=2),
        lambda p: p["data"][0].update(index=True),
        lambda p: p["data"][0].pop("index"),
        lambda p: p["data"][0].update(embedding="invalid"),
        lambda p: p["data"][0].update(embedding=[1.0]),
        lambda p: p["data"][0].update(embedding=[1.0, 10**400, 1.0]),
        lambda p: p["data"][0].update(embedding=[1.0, True, 1.0]),
        lambda p: p["data"][0].update(embedding=[1.0, math.nan, 1.0]),
        lambda p: p["data"][0].update(embedding=[1.0, math.inf, 1.0]),
        lambda p: p["usage"].update(total_tokens=-1),
        lambda p: p["usage"].update(total_tokens=1),
        lambda p: p["usage"].update(prompt_tokens=True),
        lambda p: p.pop("usage"),
    ):
        item = deepcopy(valid)
        mutation(item)
        changes.append(item)
    return changes


@pytest.mark.parametrize("payload", malformed_responses())
def test_malformed_provider_response_retains_request_id(payload):
    with patch.object(
        provider, "request_json", return_value=(payload, "req_paid")
    ) as send:
        with pytest.raises(provider.ProviderError) as error:
            provider.perform(
                "embed", {"texts": ["a", "b"], "dimensions": 3}, "secret", {}
            )
    assert error.value.code == "invalid_response"
    assert error.value.request_id == "req_paid"
    assert "secret" not in str(error.value)
    send.assert_called_once()


def test_four_maximum_vectors_fit_durable_replay_limit():
    value = -1.7976931348623157e308
    payload = response(count=4, dimensions=3072, model=MODEL_LARGE)
    for item in payload["data"]:
        item["embedding"] = [value] * 3072
    with patch.object(provider, "request_json", return_value=(payload, "req_max")):
        result = provider.perform(
            "embed", {"texts": ["a"] * 4, "model": MODEL_LARGE}, "secret", {}
        )
    # Leave space for the host's surrounding effect envelope.
    assert (
        len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode())
        + 1024
        < 512 * 1024
    )

    def nodes(value):
        if isinstance(value, dict):
            return 1 + sum(1 + nodes(child) for child in value.values())
        if isinstance(value, list):
            return 1 + sum(nodes(child) for child in value)
        return 1

    assert nodes(result) + 100 < 65536


def test_timeout_is_not_retried():
    with patch(
        "urllib.request.OpenerDirector.open", side_effect=socket.timeout()
    ) as send:
        with pytest.raises(provider.ProviderError) as error:
            provider.perform("embed", {"texts": ["a"]}, "secret", {})
    assert error.value.code == "outcome_unknown"
    assert send.call_count == 1


def test_embedding_action_contract_and_typed_ui():
    from pathlib import Path
    import yaml

    root = Path(__file__).resolve().parents[1]

    def load(name):
        return yaml.safe_load((root / name).read_text())

    operation = next(
        item
        for item in load("contracts/operation_manifest.yaml")["operations"]
        if item["operation_id"] == "embed"
    )
    inputs = {item["name"]: item for item in operation["inputs"]}
    assert inputs["texts"]["required"] is True
    assert inputs["texts"]["value_type"] == "array"
    assert inputs["texts"]["schema"]["maxItems"] == 4
    assert set(inputs["model"]["schema"]["enum"]) == {MODEL_SMALL, MODEL_LARGE}
    assert inputs["dimensions"]["value_type"] == "integer"
    assert inputs["dimensions"]["schema"]["type"] == "integer"
    assert {item["name"] for item in operation["outputs"]} == {
        "vectors",
        "model",
        "dimensions",
        "usage",
        "request_id",
    }
    form = next(
        item
        for item in load("contracts/step_ui_manifest.yaml")["forms"]
        if item["operation_id"] == "embed"
    )
    fields = {item["name"]: item for item in form["fields"]}
    assert fields["texts"]["widget_type"] == "json" and fields["texts"]["required"]
    assert fields["model"]["widget_type"] == "select"
    assert fields["dimensions"]["widget_type"] == "number"
    assert all(
        fields[name].get("help_text") for name in ("texts", "model", "dimensions")
    )
    effect = next(
        item
        for item in load("extension.yaml")["external_effects"]
        if item["operation_id"] == "embed"
    )
    assert (
        effect["effect_kind"],
        effect["idempotency"],
        effect["test_mode_behavior"],
    ) == ("paid_api_call", "required", "suppress")
    assert (
        "embed"
        in load("contracts/connection_types.yaml")["connection_types"][0][
            "capabilities"
        ]
    )


def test_embedding_runtime_suppresses_test_mode_and_requires_effect():
    import main

    action = {
        "action_id": "embed",
        "input": {"connection_ref": "conn", "texts": ["example"]},
        "target": {
            "connection": {
                "connection_id": "conn",
                "connection_type": "openai_api",
                "secrets": {"api_key": "secret"},
            }
        },
    }
    for context, code in (
        ({"test_mode": True}, "test_mode_suppressed"),
        ({}, "effect_claim_required"),
    ):
        with (
            patch.object(main, "runtime_context_from_payload"),
            patch.object(main.provider, "request_json") as send,
        ):
            result = main.handle({"runtime_context": context, "action": action})
        assert result["error_code"] == code
        assert result["definitely_no_external_effect"] is True
        send.assert_not_called()


def test_embedding_runtime_keeps_paid_error_id():
    import main

    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "embed",
            "input": {"connection_ref": "conn", "texts": ["example"], "dimensions": 3},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type": "openai_api",
                    "secrets": {"api_key": "secret"},
                }
            },
        },
    }
    with (
        patch.object(main, "runtime_context_from_payload"),
        patch.object(main.provider, "request_json", return_value=({}, "req_paid")),
    ):
        result = main.handle(payload)
    assert result["error_code"] == "invalid_response"
    assert result["provider_message_id"] == "req_paid"
    assert result["retryable"] is False
    assert result["definitely_no_external_effect"] is False


def test_exact_utf8_limit_preserves_unicode():
    original = "é" * 4000
    with patch.object(
        provider, "request_json", return_value=(response(dimensions=3), "req")
    ) as send:
        provider.perform("embed", {"texts": [original], "dimensions": 3}, "secret", {})
    assert send.call_args.args[1]["input"] == [original]


def test_missing_key_prevents_embedding_call():
    with patch.object(provider, "request_json") as send:
        with pytest.raises(provider.ProviderError) as error:
            provider.perform("embed", {"texts": ["x"]}, "", {})
    assert error.value.code == "not_configured"
    send.assert_not_called()


def test_large_integer_coordinates_are_bounded_as_floats():
    payload = response(dimensions=3)
    payload["data"][0]["embedding"] = [10**307, 0, -(10**307)]
    with patch.object(provider, "request_json", return_value=(payload, "req")):
        result = provider.perform(
            "embed", {"texts": ["x"], "dimensions": 3}, "secret", {}
        )
    assert all(type(value) is float for value in result["vectors"][0])
    assert len(json.dumps(result)) < 500


def test_portable_embedding_example_is_disabled_and_unbound():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1]
    bundle = yaml.safe_load(
        (root / "artifacts/workflows/demo_openai_embeddings.bundle.yaml").read_text()
    )
    assert bundle["schema_version"] == "platform.workflow_bundle.v2"
    assert bundle["import_hints"]["default_enabled"] is False
    workflow = bundle["workflows"][0]
    step = workflow["steps"][0]
    assert step["connector_id"] == "extension.flowsteward.openai-tools"
    assert "connector_install_id" not in step
    assert not step["connection_binding_jsonb"]
    assert step["override"]["connector"]["operation_id"] == "embed"
    assert step["input_mapping_jsonb"] == {"texts": "state.inputs.texts"}
    assert step["output_mapping_jsonb"] == {"vectors": "state.embeddings"}
