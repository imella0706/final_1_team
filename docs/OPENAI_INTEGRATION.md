# OpenAI GPT / Vision Integration

BrandMate can now route both copy generation and image-side validation through OpenAI-compatible APIs.

## Environment variables

Add these to `apps/api/.env` when using OpenAI:

```env
BRANDMATE_OPENAI_BASE_URL=https://api.openai.com/v1
BRANDMATE_OPENAI_API_KEY=sk_your_openai_key_here
BRANDMATE_OPENAI_CHAT_MODEL=gpt-5.5
BRANDMATE_OPENAI_VISION_MODEL=gpt-5.4-mini
BRANDMATE_OPENAI_IMAGE_MODEL=gpt-image-1
BRANDMATE_OPENAI_GPT_5_5_MODEL=gpt-5.5
BRANDMATE_OPENAI_GPT_5_4_MODEL=gpt-5.4
BRANDMATE_OPENAI_GPT_5_4_MINI_MODEL=gpt-5.4-mini
BRANDMATE_OPENAI_GPT_5_4_NANO_MODEL=gpt-5.4-nano
BRANDMATE_OPENAI_GPT_4_1_MINI_MODEL=gpt-4.1-mini
```

For GPT Vision validation after image generation:

```env
BRANDMATE_IMAGE_VALIDATION_ENABLED=true
BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME=gpt-5.4-mini
```

If `BRANDMATE_IMAGE_VALIDATOR_MODEL_NAME` is empty, the API uses `BRANDMATE_OPENAI_VISION_MODEL`.

## What was connected

- Ad copy model options:
  - `openai/gpt-5.5`: best quality / flagship comparison
  - `openai/gpt-5.4`: high-quality lower-cost comparison
  - `openai/gpt-5.4-mini`: faster and cheaper test candidate
  - `openai/gpt-5.4-nano`: lightest GPT test candidate
  - `openai/gpt-4.1-mini`: older baseline comparison
- Text runtime provider: `openai`
- Image model option: `openai/gpt-image-1`
- Vision QA hook: validates generated images against requested products/features using a base64 image input

## API behavior

- Copy generation still uses `/chat/completions` and JSON schema structured output when supported.
- GPT Vision validation sends the generated image as a base64 data URL.
- OpenAI image generation calls `/images/generations`.
- Requested image dimensions are mapped to common OpenAI-friendly sizes:
  - square: `1024x1024`
  - portrait: `1024x1536`
  - landscape: `1536x1024`
