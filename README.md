# OpenAI Tools

A project-scoped Flow Steward extension providing Decisions API, moderation, image generation and editing, transcription and speech. Create a project API key in the OpenAI API dashboard, open this extension’s Connection page and save it in a project-scoped OpenAI API connection, then select that connection in an Extension tools workflow step. Model access and billing are managed in OpenAI. Requests send input to OpenAI and may be charged; review data handling and model output before use. Speech must be disclosed as AI-generated. OpenAI has announced shutdown of the non-realtime speech model on 6 January 2027.

Image input artifacts must be PNG, JPEG, or WebP and are limited to 15 MB (15,000,000 bytes); audio input artifacts are limited to 24 MB. Output artifacts are limited to 25 MiB. Audio filenames must use a supported extension. A timeout or interrupted call can have an unknown outcome and is never retried automatically; check OpenAI logs before manually retrying. A successful request ID is returned with the output.

API references: https://developers.openai.com/api/reference/resources/images, https://developers.openai.com/api/reference/resources/audio, https://developers.openai.com/api/reference/resources/moderations and https://developers.openai.com/api/docs/guides/decisions.

## Example workflow

Create a workflow with an Extension tools step, select **Moderate text** and your OpenAI API connection, and map its required Text input from a workflow variable. Map `result.flagged` to a workflow variable and route it through an If step for review. This sends the supplied text to OpenAI; use sample content when testing.

An importable example is included at `artifacts/workflows/demo_openai_moderation.yaml`. Assign an OpenAI API connection before running it. The example is not deterministic and sends text to OpenAI.

## Recover an interrupted request

Find the durable external effect ID in the run's effect record. The OpenAI `X-Client-Request-Id` is `fs-` followed by the lowercase SHA-256 hex digest of the UTF-8 effect ID, without a newline. For example, calculate it locally with `printf %s 'EFFECT_ID' | shasum -a 256` and prefix the displayed digest with `fs-`. Use this ID with OpenAI support/request logs to investigate an interrupted call before deciding on reconciliation. If a response reached Flow Steward, its OpenAI request ID is recorded as the effect's provider message ID. The extension rejects transcripts whose JSON-encoded UTF-8 text exceeds 200,000 bytes rather than truncating them; a request can already have been billed.
