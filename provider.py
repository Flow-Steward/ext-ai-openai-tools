"""Bounded OpenAI API operations; no implicit retries or ambient credentials."""

import base64
from contextvars import ContextVar
import json
import math
import http.client
import socket
import urllib.error
import urllib.request
import uuid

CLIENT_REQUEST_ID = ContextVar("client_request_id", default="")

MAX_INPUT = 24_000_000
MAX_IMAGE_INPUT = 15_000_000
MAX_OUTPUT = 25 * 1024 * 1024


class ProviderError(Exception):
    def __init__(
        self,
        code,
        message,
        request_id="",
        *,
        http_status=None,
        upstream_code="",
        upstream_param="",
    ):
        super().__init__(message)
        self.code = code
        self.request_id = request_id
        self.http_status = http_status
        self.upstream_code = upstream_code
        self.upstream_param = upstream_param


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def safe_error_details(error):
    """Extract only known diagnostic tokens; never expose the provider message."""
    codes = {
        "server_error",
        "invalid_request_error",
        "invalid_api_key",
        "model_not_found",
        "rate_limit_exceeded",
        "insufficient_quota",
        "content_policy_violation",
    }
    params = {
        "image",
        "image[]",
        "images",
        "images[0].image_url",
        "prompt",
        "model",
        "size",
        "quality",
        "file",
        "voice",
        "input",
    }
    try:
        raw = error.read(8193)
        if len(raw) > 8192:
            return "", ""
        payload = json.loads(raw)
        details = payload.get("error", {}) if isinstance(payload, dict) else {}
        if not isinstance(details, dict):
            return "", ""
        code, param = details.get("code"), details.get("param")
        return (
            code if isinstance(code, str) and code in codes else "",
            param if isinstance(param, str) and param in params else "",
        )
    except (OSError, TypeError, ValueError, RecursionError, http.client.HTTPException):
        return "", ""


def request_bytes(path, body, key, content_type="application/json"):
    client_request_id = CLIENT_REQUEST_ID.get() or str(uuid.uuid4())
    request = urllib.request.Request(
        "https://api.openai.com/v1" + path,
        data=body,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": content_type,
            "X-Client-Request-Id": client_request_id,
        },
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=90
        ) as response:
            data = response.read(MAX_OUTPUT + 1)
            request_id = response.headers.get("x-request-id", "")
            if len(data) > MAX_OUTPUT:
                raise ProviderError(
                    "invalid_response",
                    "Provider response exceeds the size limit.",
                    request_id,
                )
            return data, request_id
    except urllib.error.HTTPError as exc:
        upstream_code, upstream_param = safe_error_details(exc)
        code = (
            "authentication_failed"
            if exc.code in (401, 403)
            else "rate_limited"
            if exc.code == 429
            else "outcome_unknown"
            if exc.code == 408 or exc.code >= 500
            else "provider_error"
        )
        raise ProviderError(
            code,
            (
                "The request outcome is unknown. Check OpenAI request logs before retrying."
                if code == "outcome_unknown"
                else "OpenAI rejected the request; check the connection, model access and limits."
            ),
            exc.headers.get("x-request-id", "") or client_request_id,
            http_status=exc.code,
            upstream_code=upstream_code,
            upstream_param=upstream_param,
        ) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, OSError):
        raise ProviderError(
            "outcome_unknown",
            "The request outcome is unknown. Check OpenAI request logs before retrying.",
            client_request_id,
        ) from None


def request_json(path, body, key):
    raw, request_id = request_bytes(
        path, json.dumps(body, allow_nan=False).encode(), key
    )
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        return data, request_id
    except (ValueError, UnicodeDecodeError):
        raise ProviderError(
            "invalid_response", "OpenAI returned an invalid response.", request_id
        ) from None


def text(value, field, maximum=16000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ProviderError(
            "invalid_payload",
            f"{field} must be nonempty text, at most {maximum} characters.",
        )
    return value


def image_data_url(data):
    if len(data) > MAX_IMAGE_INPUT:
        raise ProviderError(
            "invalid_payload", "Input image exceeds 15 MB (15,000,000 bytes)."
        )
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ProviderError(
            "invalid_payload", "Input image must be PNG, JPEG, or WebP."
        )
    return "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")


def multipart(fields, filename, content):
    boundary = "fs-" + uuid.uuid4().hex
    out = bytearray()
    for name, value in fields.items():
        out.extend(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    out.extend(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
    )
    out.extend(content)
    out.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(out), "multipart/form-data; boundary=" + boundary


def output_artifact(io, data, content_type, request_id):
    try:
        return io["write"](data, content_type)
    except Exception:
        raise ProviderError(
            "outcome_unknown",
            "OpenAI completed the request but the output artifact could not be saved. Check the request ID before retrying.",
            request_id,
        ) from None


def embeddings(args, key):
    texts = args.get("texts")
    if not isinstance(texts, list) or not 1 <= len(texts) <= 4:
        raise ProviderError("invalid_payload", "Provide one to four texts.")
    for value in texts:
        try:
            valid = (
                isinstance(value, str)
                and bool(value.strip())
                and len(value.encode("utf-8")) <= 8000
            )
        except UnicodeEncodeError:
            valid = False
        if not valid:
            raise ProviderError(
                "invalid_payload",
                "Each text must be nonempty valid UTF-8, at most 8,000 bytes.",
            )
    model = args.get("model", "text-embedding-3-small")
    limits = {"text-embedding-3-small": 1536, "text-embedding-3-large": 3072}
    if not isinstance(model, str) or model not in limits:
        raise ProviderError("invalid_payload", "Select a supported embedding model.")
    dimensions = args.get("dimensions", limits[model])
    if type(dimensions) is not int or not 1 <= dimensions <= limits[model]:
        raise ProviderError(
            "invalid_payload",
            "Dimensions must be an integer within the selected model's limit.",
        )
    body = {"model": model, "input": texts, "encoding_format": "float"}
    if "dimensions" in args:
        body["dimensions"] = dimensions
    response, rid = request_json("/embeddings", body, key)
    try:
        if response["model"] != model:
            raise ValueError()
        data = response["data"]
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError()
        vectors = [None] * len(texts)
        for row in data:
            index, vector = row["index"], row["embedding"]
            if (
                type(index) is not int
                or not 0 <= index < len(texts)
                or vectors[index] is not None
            ):
                raise ValueError()
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise ValueError()
            if any(
                type(value) not in (int, float) or not math.isfinite(float(value))
                for value in vector
            ):
                raise ValueError()
            vectors[index] = [float(value) for value in vector]
        usage = response["usage"]
        prompt_tokens, total_tokens = usage["prompt_tokens"], usage["total_tokens"]
        if (
            any(
                type(value) is not int or not 0 <= value <= 2_147_483_647
                for value in (prompt_tokens, total_tokens)
            )
            or total_tokens < prompt_tokens
        ):
            raise ValueError()
        return {
            "vectors": vectors,
            "model": model,
            "dimensions": dimensions,
            "usage": {"prompt_tokens": prompt_tokens, "total_tokens": total_tokens},
            "request_id": rid,
        }
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ProviderError(
            "invalid_response", "OpenAI returned invalid embeddings.", rid
        ) from None


def perform(operation, args, key, io):
    if not key or not isinstance(key, str):
        raise ProviderError(
            "not_configured", "Add an OpenAI API key to the selected connection."
        )
    if operation == "embed":
        return embeddings(args, key)
    if operation in ("predicate", "choice", "score"):
        prompt = text(args.get("prompt"), "prompt")
        evidence = text(args.get("evidence"), "evidence")
        question = {"type": operation, "name": "decision", "instructions": prompt}
        if operation in ("choice", "score"):
            values = args.get("choices" if operation == "choice" else "levels")
            field = "choices" if operation == "choice" else "levels"
            if (
                not isinstance(values, list)
                or not 2 <= len(values) <= 20
                or any(
                    not isinstance(c, str) or not c.strip() or len(c) > 100
                    for c in values
                )
                or len(set(values)) != len(values)
            ):
                raise ProviderError(
                    "invalid_payload",
                    f"{field} must contain 2–20 distinct nonempty strings, each at most 100 characters.",
                )
            question[field] = [
                {
                    "value" if operation == "choice" else "label": value,
                    "description": value,
                }
                for value in values
            ]
        response, rid = request_json(
            "/decisions",
            {"model": "gpt-6-luna", "input": evidence, "questions": [question]},
            key,
        )
        try:
            answer = response["answers"][0]
            if answer["type"] != operation or answer["name"] != "decision":
                raise ValueError()
            value = answer[
                {"predicate": "probability", "choice": "choice", "score": "score"}[
                    operation
                ]
            ]
            valid = (
                (operation == "choice" and value in values)
                or (
                    operation == "predicate"
                    and type(value) in (int, float)
                    and 0 <= value <= 1
                )
                or (
                    operation == "score"
                    and type(value) in (int, float)
                    and 0 <= value <= len(values) - 1
                )
            )
            if not valid:
                raise ValueError()
        except (KeyError, TypeError, ValueError, IndexError):
            raise ProviderError(
                "invalid_response",
                f"OpenAI returned an invalid {operation} answer or refused the request.",
                rid,
            ) from None
        return {"value": value, "request_id": rid}
    if operation in ("moderate_text", "moderate_image"):
        if operation == "moderate_text":
            content = text(args.get("text"), "text")
        else:
            data = io["read"](args.get("artifact_handle"))
            content = [
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url(data)},
                }
            ]
        response, rid = request_json(
            "/moderations", {"model": "omni-moderation-latest", "input": content}, key
        )
        try:
            item = response["results"][0]
            if type(item["flagged"]) is not bool or not isinstance(
                item["categories"], dict
            ):
                raise ValueError()
            return {
                "flagged": item["flagged"],
                "categories": item["categories"],
                "request_id": rid,
            }
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(
                "invalid_response", "OpenAI returned an invalid moderation result.", rid
            ) from None
    if operation == "generate_image":
        response, rid = request_json(
            "/images/generations",
            {
                "model": "gpt-image-2.5-sunburst",
                "prompt": text(args.get("prompt"), "prompt", 32000),
                "size": "1024x1024",
                "n": 1,
            },
            key,
        )
        try:
            data = base64.b64decode(response["data"][0]["b64_json"], validate=True)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(
                "invalid_response", "OpenAI returned an invalid image.", rid
            ) from None
        return {
            "output_artifact_handle": output_artifact(io, data, "image/png", rid),
            "request_id": rid,
        }
    if operation == "edit_image":
        image = io["read"](args.get("artifact_handle"))
        prompt = text(args.get("prompt"), "prompt", 32000)
        response, rid = request_json(
            "/images/edits",
            {
                "model": "gpt-image-2.5-sunburst",
                "prompt": prompt,
                "size": "1024x1024",
                "n": 1,
                "images": [{"image_url": image_data_url(image)}],
            },
            key,
        )
        try:
            data = base64.b64decode(response["data"][0]["b64_json"], validate=True)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError(
                "invalid_response", "OpenAI returned an invalid image.", rid
            ) from None
        return {
            "output_artifact_handle": output_artifact(io, data, "image/png", rid),
            "request_id": rid,
        }
    if operation == "transcribe":
        audio = io["read"](args.get("artifact_handle"))
        filename = text(args.get("filename"), "filename", 128)
        if not filename.lower().endswith(
            (".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm")
        ):
            raise ProviderError(
                "invalid_payload",
                "filename must use a supported audio extension: mp3, mp4, mpeg, mpga, m4a, wav or webm.",
            )
        body, content_type = multipart(
            {"model": "gpt-transcribe"},
            "audio." + filename.rsplit(".", 1)[1].lower(),
            audio,
        )
        raw, rid = request_bytes("/audio/transcriptions", body, key, content_type)
        try:
            result = json.loads(raw)["text"]
            if (
                not isinstance(result, str)
                or len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > 200000
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ProviderError(
                "invalid_response", "OpenAI returned an invalid transcript.", rid
            ) from None
        return {"text": result, "request_id": rid}
    if operation == "speech":
        voice = args.get("voice", "alloy")
        if voice not in (
            "alloy",
            "ash",
            "ballad",
            "coral",
            "echo",
            "fable",
            "nova",
            "onyx",
            "sage",
            "shimmer",
            "verse",
        ):
            raise ProviderError(
                "invalid_payload", "voice must be one of the listed voices."
            )
        body = json.dumps(
            {
                "model": "gpt-4o-mini-tts",
                "input": text(args.get("text"), "text", 4096),
                "voice": voice,
                "response_format": "mp3",
            }
        ).encode()
        audio, rid = request_bytes("/audio/speech", body, key)
        return {
            "output_artifact_handle": output_artifact(io, audio, "audio/mpeg", rid),
            "request_id": rid,
        }
    raise ProviderError("invalid_payload", "Select a supported OpenAI operation.")
