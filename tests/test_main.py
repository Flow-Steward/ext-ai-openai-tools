from unittest.mock import patch

import main


def test_test_mode_never_makes_paid_request():
    payload = {
        "runtime_context": {"test_mode": True},
        "action": {
            "action_id": "speech",
            "input": {"connection_ref": "conn", "text": "hello"},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type_id": "openai_api",
                    "secrets": {"api_key": "secret"},
                }
            },
        },
    }
    with (
        patch.object(main, "runtime_context_from_payload"),
        patch.object(main.provider, "perform") as perform,
    ):
        response = main.handle(payload)
    assert response["ok"] is False
    assert response["error_code"] == "test_mode_suppressed"
    assert response["definitely_no_external_effect"] is True
    perform.assert_not_called()


def test_missing_effect_claim_prevents_paid_operation():
    payload = {
        "runtime_context": {},
        "action": {
            "action_id": "speech",
            "input": {"connection_ref": "conn", "text": "hello"},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type_id": "openai_api",
                    "secrets": {"api_key": "secret"},
                }
            },
        },
    }
    with (
        patch.object(main, "runtime_context_from_payload"),
        patch.object(main.provider, "perform") as perform,
    ):
        response = main.handle(payload)
    assert response["error_code"] == "effect_claim_required"
    assert response["definitely_no_external_effect"] is True
    perform.assert_not_called()


def test_claim_id_is_stable_request_correlation():
    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "speech",
            "input": {"connection_ref": "conn", "text": "hello"},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type_id": "openai_api",
                    "secrets": {"api_key": "secret"},
                }
            },
        },
    }
    captured = []

    def fake_perform(*_):
        captured.append(main.provider.CLIENT_REQUEST_ID.get())
        return {}

    with (
        patch.object(main, "runtime_context_from_payload"),
        patch.object(main.provider, "perform", side_effect=fake_perform),
    ):
        assert main.handle(payload)["ok"] is True
        assert main.handle(payload)["ok"] is True
    assert captured[0] == captured[1]
    assert captured[0].startswith("fs-")
    assert "effect-1" not in captured[0]


def test_upstream_request_id_exposed_as_effect_metadata():
    payload = {
        "runtime_context": {"external_effect_id": "effect-1"},
        "action": {
            "action_id": "speech",
            "input": {"connection_ref": "conn", "text": "hello"},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type_id": "openai_api",
                    "secrets": {"api_key": "secret"},
                }
            },
        },
    }
    with (
        patch.object(main, "runtime_context_from_payload"),
        patch.object(
            main.provider, "perform", return_value={"request_id": "req_openai"}
        ),
    ):
        response = main.handle(payload)
    assert response["provider_message_id"] == "req_openai"
