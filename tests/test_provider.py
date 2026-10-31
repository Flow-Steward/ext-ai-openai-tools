import socket
from unittest.mock import patch

import pytest
import provider


def test_decision_schema_and_result():
    response = {
        "answers": [{"type": "predicate", "name": "decision", "probability": 0.9}]
    }
    with patch.object(
        provider, "request_json", return_value=(response, "req_123")
    ) as request:
        result = provider.perform(
            "predicate",
            {"prompt": "Is it urgent?", "evidence": "A ticket"},
            "secret",
            {},
        )
    assert result == {"value": 0.9, "request_id": "req_123"}
    assert request.call_args.args[0] == "/decisions"
    assert request.call_args.args[1]["questions"][0]["type"] == "predicate"


def test_choice_rejects_value_outside_requested_options():
    response = {"answers": [{"type": "choice", "name": "decision", "choice": "other"}]}
    with patch.object(provider, "request_json", return_value=(response, "r")):
        with pytest.raises(provider.ProviderError, match="choice"):
            provider.perform(
                "choice",
                {"prompt": "Pick", "evidence": "A ticket", "choices": ["a", "b"]},
                "secret",
                {},
            )


def test_moderation_sends_expected_model():
    with patch.object(
        provider,
        "request_json",
        return_value=({"results": [{"flagged": True, "categories": {}}]}, "r"),
    ) as request:
        assert (
            provider.perform("moderate_text", {"text": "example"}, "secret", {})[
                "flagged"
            ]
            is True
        )
    assert request.call_args.args[1]["model"] == "omni-moderation-latest"


def test_no_retry_after_timeout():
    with patch(
        "urllib.request.OpenerDirector.open", side_effect=socket.timeout()
    ) as send:
        with pytest.raises(provider.ProviderError, match="outcome is unknown"):
            provider.request_json("/responses", {}, "secret")
    assert send.call_count == 1


def test_reject_missing_key_before_request():
    with patch.object(provider, "request_json") as send:
        with pytest.raises(provider.ProviderError, match="API key"):
            provider.perform("predicate", {"prompt": "x", "evidence": "y"}, "", {})
    send.assert_not_called()


def test_score_rejects_out_of_range():
    response = {"answers": [{"type": "score", "name": "decision", "score": 2.2}]}
    with patch.object(provider, "request_json", return_value=(response, "r")):
        with pytest.raises(provider.ProviderError, match="score"):
            provider.perform(
                "score",
                {
                    "prompt": "Rate quality",
                    "evidence": "A ticket",
                    "levels": ["low", "high"],
                },
                "secret",
                {},
            )


def test_generate_image_writes_decoded_artifact():
    response = {"data": [{"b64_json": "aW1hZ2U="}]}
    writes = []
    with patch.object(provider, "request_json", return_value=(response, "r")):
        result = provider.perform(
            "generate_image",
            {"prompt": "A tree"},
            "secret",
            {"write": lambda data, mime: writes.append((data, mime)) or "a"},
        )
    assert writes == [(b"image", "image/png")]
    assert result == {"output_artifact_handle": "a", "request_id": "r"}


def test_image_edit_uses_image_multipart_field():
    response = b'{"data":[{"b64_json":"aW1hZ2U="}]}'
    with patch.object(
        provider, "request_bytes", return_value=(response, "r")
    ) as request:
        provider.perform(
            "edit_image",
            {"prompt": "Edit", "artifact_handle": "in"},
            "secret",
            {"read": lambda _: b"png", "write": lambda *_: "out"},
        )
    assert b'name="image";' in request.call_args.args[1]
    assert request.call_args.args[0] == "/images/edits"


def test_transcription_requires_supported_extension():
    with pytest.raises(provider.ProviderError, match="filename"):
        provider.perform(
            "transcribe",
            {"artifact_handle": "a", "filename": "audio.exe"},
            "secret",
            {"read": lambda _: b"audio"},
        )


def test_speech_rejects_unknown_voice_before_request():
    with patch.object(provider, "request_bytes") as request:
        with pytest.raises(provider.ProviderError, match="voice"):
            provider.perform(
                "speech", {"text": "hello", "voice": "invalid"}, "secret", {}
            )
    request.assert_not_called()


def test_moderate_image_uses_data_url():
    with patch.object(
        provider,
        "request_json",
        return_value=({"results": [{"flagged": False, "categories": {}}]}, "r"),
    ) as request:
        provider.perform(
            "moderate_image",
            {"artifact_handle": "a"},
            "secret",
            {"read": lambda _: b"png"},
        )
    assert (
        request.call_args.args[1]["input"][0]["image_url"]["url"]
        == "data:image/png;base64,cG5n"
    )


def test_speech_saves_mp3():
    with patch.object(
        provider, "request_bytes", return_value=(b"mp3", "req_speech")
    ) as request:
        result = provider.perform(
            "speech",
            {"text": "hello", "voice": "coral"},
            "secret",
            {"write": lambda data, mime: mime},
        )
    assert request.call_args.args[0] == "/audio/speech"
    assert result == {
        "output_artifact_handle": "audio/mpeg",
        "request_id": "req_speech",
    }


def test_transcription_returns_text():
    with patch.object(
        provider, "request_bytes", return_value=(b'{"text":"hello"}', "req_audio")
    ) as request:
        result = provider.perform(
            "transcribe",
            {"artifact_handle": "a", "filename": "voice.wav"},
            "secret",
            {"read": lambda _: b"audio"},
        )
    assert request.call_args.args[0] == "/audio/transcriptions"
    assert b"gpt-transcribe" in request.call_args.args[1]
    assert result == {"text": "hello", "request_id": "req_audio"}


def test_artifact_save_failure_retains_paid_request_id():
    def fail(*_):
        raise OSError("disk error")

    with patch.object(provider, "request_bytes", return_value=(b"audio", "req_paid")):
        with pytest.raises(provider.ProviderError) as error:
            provider.perform("speech", {"text": "hello"}, "secret", {"write": fail})
    assert error.value.code == "outcome_unknown"
    assert error.value.request_id == "req_paid"


def test_authentication_error_is_safe():
    from urllib.error import HTTPError

    error = HTTPError(
        "https://api.openai.com/v1/test",
        401,
        "Unauthorized",
        {"x-request-id": "req_auth"},
        None,
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=error):
        with pytest.raises(provider.ProviderError) as result:
            provider.request_json("/test", {}, "secret")
    assert result.value.code == "authentication_failed"
    assert result.value.request_id == "req_auth"
    assert "secret" not in str(result.value)


def test_decision_keeps_evidence_separate_from_instructions():
    response = {
        "answers": [{"type": "predicate", "name": "decision", "probability": 0.5}]
    }
    with patch.object(
        provider, "request_json", return_value=(response, "r")
    ) as request:
        provider.perform(
            "predicate",
            {
                "prompt": "Does it request a refund?",
                "evidence": "Please refund my order.",
            },
            "secret",
            {},
        )
    assert request.call_args.args[1]["input"] == "Please refund my order."
    assert (
        request.call_args.args[1]["questions"][0]["instructions"]
        == "Does it request a refund?"
    )
