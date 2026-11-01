# OpenAI Tools

Requires extension runtime contract 1.4.0 or later; compatibility is checked during installation.

A project-scoped Flow Steward extension providing Decisions API, moderation, image generation and editing, transcription, speech and text embeddings. Create a project API key in the OpenAI API dashboard, open this extension’s Connection page and save it in a project-scoped OpenAI API connection, then select that connection in an Extension tools workflow step. Model access and billing are managed in OpenAI. Requests send input to OpenAI and may be charged; review data handling and model output before use. Speech must be disclosed as AI-generated. OpenAI has announced shutdown of the non-realtime speech model on 6 January 2027.

Image input artifacts must be PNG, JPEG, or WebP and are limited to 15 MB (15,000,000 bytes); audio input artifacts are limited to 24 MB. Output artifacts are limited to 25 MiB. Audio filenames must use a supported extension. A timeout or interrupted call can have an unknown outcome and is never retried automatically; check OpenAI logs before manually retrying. A successful request ID is returned with the output.

API references: https://developers.openai.com/api/reference/resources/images, https://developers.openai.com/api/reference/resources/audio, https://developers.openai.com/api/reference/resources/moderations and https://developers.openai.com/api/docs/guides/decisions.

## Embeddings

**Embed texts** accepts a JSON array of 1–4 nonempty texts, each at most 8,000 UTF-8 bytes. This conservative byte limit is below the provider's 8,192-token per-input limit. Texts are sent unchanged; the extension does not truncate or chunk them. OpenAI charges per input token; avoid sending sensitive data unless appropriate for your project. Choose text-embedding-3-small (default, 1,536 dimensions) or text-embedding-3-large (3,072 dimensions). Optional dimensions must be an integer from 1 through the selected model's default size. The `vectors` output matches input order; `model`, `dimensions`, `usage` and `request_id` accompany it. Use the same model and dimensions for all vectors in a vector index.

Import `artifacts/workflows/demo_openai_embeddings.bundle.yaml` as a disabled draft using Flow Steward’s workflow import, map its extension dependency to the installed OpenAI Tools instance, and select a project OpenAI connection in the imported step before running it. The example sends its input to OpenAI and may incur charges.

Embedding API: https://developers.openai.com/api/reference/resources/embeddings/methods/create

## Example workflow

Create a workflow with an Extension tools step, select **Moderate text** and your OpenAI API connection, and map its required Text input from a workflow variable. Map the **flagged** output to a workflow variable and route it through an If step for review. This sends the supplied text to OpenAI; use sample content when testing.

The extension includes a disabled projected example. To import a separate disabled draft, use `artifacts/workflows/demo_openai_moderation.bundle.yaml` with Flow Steward’s workflow import. Map its OpenAI extension dependency to the installed OpenAI Tools instance, then select a project OpenAI API connection in the imported step before enabling or running it. The example is not deterministic and sends text to OpenAI.

## Recover an interrupted request

Find the durable external effect ID in the run's effect record. The OpenAI `X-Client-Request-Id` is `fs-` followed by the lowercase SHA-256 hex digest of the UTF-8 effect ID, without a newline. For example, calculate it locally with `printf %s 'EFFECT_ID' | shasum -a 256` and prefix the displayed digest with `fs-`. Use this ID with OpenAI support/request logs to investigate an interrupted call before deciding on reconciliation. If a response reached Flow Steward, its OpenAI request ID is recorded as the effect's provider message ID. The extension rejects transcripts whose JSON-encoded UTF-8 text exceeds 200,000 bytes rather than truncating them; a request can already have been billed.
