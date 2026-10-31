import json

print(
    json.dumps(
        {"ok": True, "status": "healthy", "extension_id": "flowsteward.openai-tools"}
    )
)
