# Workflow actions

Save an OpenAI API key in a project OpenAI API connection. Select that connection on the Extension tools step; provider model access and billing apply. Artifact inputs must come from a previous workflow step.

For review routing, run Check text for flagged content and branch on flagged. For retrieval, map the vectors output from Generate text embeddings into a vector-store action in the same input order. Media actions return an artifact handle for later steps.

Select the named action in an Extension tools step. Map workflow values to its inputs and map the returned fields needed by later steps. Examples below contain sample data; replace artifact handles and embedding values with actual earlier-step outputs.

## Estimate a yes probability

Evaluate a question against supplied evidence using OpenAI. Returns value as a number from 0 to 1 representing yes probability, rather than a boolean; choose a threshold in a later workflow step.

- **Decision instructions**: Explain the question to evaluate using Evidence. Maximum 16000 characters.
- **Evidence to evaluate**: Text the decision should evaluate, such as a customer message. Maximum 16000 characters.

Example input values:

```json
{
  "prompt": "Does the customer request a refund?",
  "evidence": "I would like to return my order and get a refund."
}
```

## Choose an option from evidence

Use OpenAI to select one of 2–20 supplied option strings based on instructions and evidence. Returns the selected string as value.

- **Decision instructions**: Explain the question to evaluate using Evidence. Maximum 16000 characters.
- **Evidence to evaluate**: Text the decision should evaluate, such as a customer message. Maximum 16000 characters.
- **Allowed options (JSON array)**: Supply 2–20 distinct nonempty strings, each at most 100 characters. The returned value is one of these exact strings.

Example input values:

```json
{
  "prompt": "Classify the customer request by topic.",
  "evidence": "I would like to return my order and get a refund.",
  "choices": [
    "billing",
    "technical",
    "general"
  ]
}
```

## Score evidence against ordered levels

Use OpenAI to score evidence on 2–20 supplied levels in order. Returns a numeric value from 0 through level count minus one; the score can fall between levels.

- **Decision instructions**: Explain the question to evaluate using Evidence. Maximum 16000 characters.
- **Evidence to evaluate**: Text the decision should evaluate, such as a customer message. Maximum 16000 characters.
- **Levels from lowest to highest (JSON array)**: Supply 2–20 distinct nonempty labels, each at most 100 characters, ordered from lowest to highest. A numeric score ranges from 0 through level count minus one.

Example input values:

```json
{
  "prompt": "Rate how urgently this customer request needs attention.",
  "evidence": "I would like to return my order and get a refund.",
  "levels": [
    "routine",
    "important",
    "urgent"
  ]
}
```

## Check text for flagged content

Send text to OpenAI moderation and return flagged plus category flags. Use the outputs to route content for review; this action does not block or remove content.

- **Text to check**: Text for content moderation, at most 16000 characters. Inspect flagged and categories in a later workflow step.

Example input values:

```json
{
  "text": "A customer message to review."
}
```

## Check an image for flagged content

Send a PNG, JPEG or WebP artifact to OpenAI moderation and return flagged plus category flags. The action does not modify the image or make a workflow routing decision.

- **Source image artifact**: Map an image artifact from an earlier step: PNG, JPEG or WebP, up to 15000000 bytes.

Example input values:

```json
{
  "artifact_handle": "artifact:input"
}
```

In the workflow editor, select the source artifact from the earlier step. `artifact:input` illustrates the mapped handle; replace it with the actual handle supplied by that step.

## Generate an image from a prompt

Send a description to OpenAI and save the generated image as a workflow artifact. Returns output_artifact_handle and the provider request ID.

- **Image description**: Describe the image to generate, including subject, composition and appearance. Maximum 32000 characters.

Example input values:

```json
{
  "prompt": "A studio photograph of a blue ceramic cup on a white background."
}
```

## Edit an image using instructions

Send a source image artifact and editing instructions to OpenAI. Saves the edited image as a new workflow artifact and returns its handle.

- **Source image artifact**: Map an image artifact from an earlier step: PNG, JPEG or WebP, up to 15000000 bytes.
- **Image editing instructions**: Describe changes to the selected source image. Maximum 32000 characters.

Example input values:

```json
{
  "artifact_handle": "artifact:input",
  "prompt": "Replace the background with a plain white studio background."
}
```

In the workflow editor, select the source artifact from the earlier step. `artifact:input` illustrates the mapped handle; replace it with the actual handle supplied by that step.

## Transcribe an audio file to text

Send an audio artifact and its filename to OpenAI transcription. Returns transcript text and a provider request ID; supply the real supported audio extension.

- **Audio artifact**: Map an audio artifact from an earlier workflow step, up to 24 MB. Supply its actual filename below.
- **Original audio filename**: Use the real audio extension: mp3, mp4, mpeg, mpga, m4a, wav or webm. The extension is required for the upload.

Example input values:

```json
{
  "artifact_handle": "artifact:input",
  "filename": "meeting.wav"
}
```

In the workflow editor, select the source artifact from the earlier step. `artifact:input` illustrates the mapped handle; replace it with the actual handle supplied by that step.

## Generate speech from text

Send up to 4096 characters to OpenAI and save the generated speech as an audio artifact. Select a voice; disclose AI-generated speech to listeners.

- **Text to speak**: Text to synthesize, at most 4096 characters. Output is an audio artifact; inform listeners that the voice is AI-generated.
- **Speech voice**: Choose an available voice; alloy is the default. The voice changes the generated speech, not the supplied wording.

Example input values:

```json
{
  "text": "Your order is ready for collection."
}
```

## Generate text embeddings

Use OpenAI to generate one numeric embedding per input text, in order. Accepts 1–4 texts and returns vectors, model, dimensions, usage and request ID; use matching model and dimensions in your vector store.

- **Texts to embed (JSON array)**: Supply 1–4 nonempty strings, each at most 8000 UTF-8 bytes. No automatic splitting or truncation. Returned vectors preserve this order.
- **Embedding model**: Default: text-embedding-3-small (1536 dimensions). Large defaults to 3072. Use the same model for stored text and search questions.
- **Embedding dimensions**: Optional integer: 1–1536 for small or 1–3072 for large. Blank uses the model default. Match your vector-store dimensions exactly.

Example input values:

```json
{
  "texts": [
    "Refunds are available within 30 days."
  ],
  "dimensions": 1536
}
```
