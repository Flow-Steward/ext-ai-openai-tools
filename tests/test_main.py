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
