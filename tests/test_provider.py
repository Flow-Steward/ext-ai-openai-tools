import json

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
            {"read": lambda _: b"\x89PNG\r\n\x1a\n"},
        )
    assert (
        request.call_args.args[1]["input"][0]["image_url"]["url"]
        == "data:image/png;base64,iVBORw0KGgo="
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


def test_multibyte_transcript_over_replay_budget_fails_without_truncation():
    body = json.dumps({"text": "界" * 70000}, ensure_ascii=False).encode()
    with patch.object(provider, "request_bytes", return_value=(body, "req_long")):
        with pytest.raises(provider.ProviderError) as error:
            provider.perform(
                "transcribe",
                {"artifact_handle": "a", "filename": "voice.wav"},
                "secret",
                {"read": lambda _: b"audio"},
            )
    assert error.value.request_id == "req_long"
    assert error.value.code == "invalid_response"


def test_http_error_preserves_safe_structured_diagnostics_without_echoing_body():
    import io
    from urllib.error import HTTPError

    body = (
        b'{"error":{"code":"server_error","param":"image","message":"secret echoed"}}'
    )
    error = HTTPError(
        "https://api.openai.com/v1/images/edits",
        502,
        "failure",
        {"x-request-id": "req_safe"},
        io.BytesIO(body),
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=error) as send:
        with pytest.raises(provider.ProviderError) as result:
            provider.request_bytes("/images/edits", b"request", "secret")
    assert send.call_count == 1
    assert result.value.code == "outcome_unknown"
    assert result.value.request_id == "req_safe"
    assert result.value.http_status == 502
    assert result.value.upstream_code == "server_error"
    assert result.value.upstream_param == "image"
    assert "secret echoed" not in str(result.value)


def test_http_error_rejects_untrusted_diagnostic_values():
    import io
    from urllib.error import HTTPError

    body = (
        b'{"error":{"code":"secret_key","param":"secret_key","message":"secret_key"}}'
    )
    error = HTTPError(
        "https://api.openai.com/v1/images/edits", 400, "failure", {}, io.BytesIO(body)
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=error):
        with pytest.raises(provider.ProviderError) as result:
            provider.request_bytes("/images/edits", b"request", "secret_key")
    assert result.value.http_status == 400
    assert result.value.upstream_code == ""
    assert result.value.upstream_param == ""
    assert "secret_key" not in str(result.value)


def test_unparseable_or_large_error_body_is_discarded():
    import io
    from urllib.error import HTTPError

    for body in (b"not json", b"x" * 9000):
        error = HTTPError(
            "https://api.openai.com/v1/test", 502, "failure", {}, io.BytesIO(body)
        )
        with patch("urllib.request.OpenerDirector.open", side_effect=error):
            with pytest.raises(provider.ProviderError) as result:
                provider.request_bytes("/test", b"request", "secret")
        assert result.value.http_status == 502
        assert result.value.upstream_code == ""
        assert result.value.upstream_param == ""


def test_edit_image_serializes_documented_json_data_url_and_png_bytes():
    import base64
    from email.message import Message
    from io import BytesIO

    image_bytes = b"\x89PNG\r\n\x1a\nsynthetic"
    response = BytesIO(b'{"data":[{"b64_json":"aW1hZ2U="}]}')
    response.headers = Message()
    response.headers["x-request-id"] = "req_edit"
    with patch("urllib.request.OpenerDirector.open", return_value=response) as send:
        result = provider.perform(
            "edit_image",
            {"prompt": "Make it green", "artifact_handle": "a"},
            "secret",
            {"read": lambda _: image_bytes, "write": lambda *_: "out"},
        )
    request = send.call_args.args[0]
    assert request.full_url == "https://api.openai.com/v1/images/edits"
    assert request.get_header("Content-type") == "application/json"
    body = json.loads(request.data)
    assert body["model"] == "gpt-image-2.5-sunburst"
    assert body["n"] == 1 and body["size"] == "1024x1024"
    assert body["prompt"] == "Make it green"
    prefix, encoded = body["images"][0]["image_url"].split(",", 1)
    assert prefix == "data:image/png;base64"
    assert base64.b64decode(encoded, validate=True) == image_bytes
    assert result["request_id"] == "req_edit"


def test_moderate_image_uses_jpeg_media_type():
    jpeg = b"\xff\xd8\xffsynthetic"
    with patch.object(
        provider,
        "request_json",
        return_value=({"results": [{"flagged": False, "categories": {}}]}, "r"),
    ) as send:
        provider.perform(
            "moderate_image",
            {"artifact_handle": "a"},
            "secret",
            {"read": lambda _: jpeg},
        )
    assert send.call_args.args[1]["input"][0]["image_url"]["url"].startswith(
        "data:image/jpeg;base64,"
    )


@pytest.mark.parametrize("operation", ["moderate_image", "edit_image"])
def test_image_operations_reject_unsupported_artifact_before_request(operation):
    with patch.object(provider, "request_json") as send:
        with pytest.raises(provider.ProviderError) as result:
            provider.perform(
                operation,
                {"artifact_handle": "a", "prompt": "edit"},
                "secret",
                {"read": lambda _: b"%PDF-1.7"},
            )
    assert result.value.code == "invalid_payload"
    assert not result.value.request_id
    send.assert_not_called()


def test_webp_data_url_uses_image_webp():
    import base64

    data = b"RIFF\x04\x00\x00\x00WEBPsynthetic"
    result = provider.image_data_url(data)
    assert result.startswith("data:image/webp;base64,")
    assert base64.b64decode(result.split(",", 1)[1]) == data


@pytest.mark.parametrize("operation", ["moderate_image", "edit_image"])
def test_oversized_image_is_rejected_before_upstream_request(operation):
    data = b"\x89PNG\r\n\x1a\n" + b"x" * (15_000_001 - 8)
    with patch.object(provider, "request_json") as send:
        with pytest.raises(provider.ProviderError) as error:
            provider.perform(
                operation,
                {"artifact_handle": "a", "prompt": "edit"},
                "secret",
                {"read": lambda _: data},
            )
    assert error.value.code == "invalid_payload"
    assert "15 MB" in str(error.value)
    send.assert_not_called()


def test_image_byte_limit_fits_documented_data_url_length():
    limit = provider.MAX_IMAGE_INPUT
    longest_prefix = len("data:image/jpeg;base64,")
    assert longest_prefix + 4 * ((limit + 2) // 3) <= 20_971_520


def test_diagnostic_parse_failures_preserve_status_and_request_id():
    import http.client
    import io
    from urllib.error import HTTPError

    class BrokenRead:
        def read(self, _amount):
            raise http.client.IncompleteRead(b"partial")

        def close(self):
            pass

    for stream in (BrokenRead(), io.BytesIO(b"[" * 1500 + b"]" * 1500)):
        failure = HTTPError(
            "https://api.openai.com/v1/images/edits",
            502,
            "failure",
            {"x-request-id": "req_safe"},
            stream,
        )
        with patch("urllib.request.OpenerDirector.open", side_effect=failure):
            with pytest.raises(provider.ProviderError) as result:
                provider.request_bytes("/images/edits", b"request", "secret")
        assert result.value.code == "outcome_unknown"
        assert result.value.http_status == 502
        assert result.value.request_id == "req_safe"


def test_known_nested_image_parameter_is_safe_diagnostic():
    import io
    from urllib.error import HTTPError

    failure = HTTPError(
        "https://api.openai.com/v1/images/edits",
        400,
        "failure",
        {},
        io.BytesIO(b'{"error":{"param":"images[0].image_url"}}'),
    )
    with patch("urllib.request.OpenerDirector.open", side_effect=failure):
        with pytest.raises(provider.ProviderError) as result:
            provider.request_bytes("/images/edits", b"request", "secret")
    assert result.value.upstream_param == "images[0].image_url"
