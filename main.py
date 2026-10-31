"""Flow Steward subprocess entrypoint for project-scoped OpenAI tools."""

import hashlib
import json
import sys

from flowsteward_extension_sdk import runtime_context_from_payload  # type: ignore[import-untyped]
from flowsteward_extension_sdk.artifacts import (  # type: ignore[import-untyped]
    ArtifactAccessError,
    stream_artifact_bytes,
    write_artifact_bytes,
)

import provider


def handle(payload):
    try:
        runtime_context_from_payload(payload)
        runtime = payload.get("runtime_context", {})
        if not isinstance(runtime.get("test_mode", False), bool):
            raise provider.ProviderError(
                "invalid_payload", "test_mode must be a boolean."
            )
        if runtime.get("test_mode", False):
            raise provider.ProviderError(
                "test_mode_suppressed", "OpenAI calls are suppressed in test mode."
            )
        effect_id = runtime.get("external_effect_id")
        if (
            not isinstance(effect_id, str)
            or not effect_id.strip()
            or len(effect_id) > 512
        ):
            raise provider.ProviderError(
                "effect_claim_required",
                "A durable effect claim is required before calling OpenAI.",
            )
        provider.CLIENT_REQUEST_ID.set(
            "fs-" + hashlib.sha256(effect_id.encode()).hexdigest()
        )
        action = payload.get("action", {})
        args = action.get("input", {})
        connection = action.get("target", {}).get("connection", {})
        if not isinstance(args, dict) or not isinstance(connection, dict):
            raise provider.ProviderError(
                "invalid_payload", "Action input and connection are required."
            )
        if (
            not args.get("connection_ref")
            or args["connection_ref"] != connection.get("connection_id")
            or connection.get("connection_type") != "openai_api"
        ):
            raise provider.ProviderError(
                "invalid_connection", "Select the matching OpenAI API connection."
            )
        key = connection.get("secrets", {}).get("api_key", "")

        def read(handle):
            if not isinstance(handle, str) or not handle:
                raise provider.ProviderError(
                    "invalid_payload", "Select an input file artifact."
                )
            data = bytearray()
            for chunk in stream_artifact_bytes(
                payload,
                artifact_id=handle,
                binding_key="source_file",
                timeout_seconds=10,
            ):
                data.extend(chunk)
                if len(data) > provider.MAX_INPUT:
                    raise provider.ProviderError(
                        "invalid_payload", "Input file exceeds 24 MB."
                    )
            return bytes(data)

        def write(data, content_type):
            if not data or len(data) > provider.MAX_OUTPUT:
                raise provider.ProviderError(
                    "invalid_response", "Output file is empty or exceeds 25 MiB."
                )
            return write_artifact_bytes(
                payload,
                data,
                binding_key="output_artifact_handle",
                content_type=content_type,
                timeout_seconds=10,
            )["artifact_handle"]

        result = provider.perform(
            action.get("action_id"), args, key, {"read": read, "write": write}
        )
        return {
            "ok": True,
            "result": result,
            "errors": [],
            "provider_message_id": result.get("request_id", ""),
        }
    except provider.ProviderError as exc:
        return {
            "ok": False,
            "result": {},
            "error_code": exc.code,
            "error": str(exc),
            "errors": [{"code": exc.code, "message": str(exc)}],
            "request_id": exc.request_id,
            "provider_message_id": exc.request_id,
            "retryable": False,
            "definitely_no_external_effect": exc.code
            in {
                "test_mode_suppressed",
                "effect_claim_required",
                "invalid_payload",
                "invalid_connection",
                "not_configured",
            }
            and not exc.request_id,
        }
    except (ArtifactAccessError, ValueError, KeyError, TypeError):
        return {
            "ok": False,
            "result": {},
            "error_code": "artifact_access_failed",
            "error": "Unable to access the granted artifact or connection.",
            "errors": [
                {
                    "code": "artifact_access_failed",
                    "message": "Unable to access the granted artifact or connection.",
                }
            ],
        }


def main():
    try:
        raw = sys.stdin.buffer.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError()
        response = handle(payload)
    except (ValueError, UnicodeDecodeError):
        response = {
            "ok": False,
            "result": {},
            "error_code": "invalid_payload",
            "error": "A valid action envelope is required.",
            "errors": [
                {
                    "code": "invalid_payload",
                    "message": "A valid action envelope is required.",
                }
            ],
        }
    print(json.dumps(response, allow_nan=False))
    return 0 if response["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
