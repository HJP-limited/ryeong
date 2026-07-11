# Embedding Migration Notes

Date: 2026-07-10
Branch: `llm-integration-work`

## What is already done

- Split the app into three bottom tabs:
  - `명함` for keyword-only card search
  - `채팅` for natural-language hybrid search + LLM
  - `모델` for model import and diagnostics
- Kept the LLM path on `LiteRT-LM` with `functiongemma_270m.litertlm`
- Added keyword search normalization and ranking logic
- Added Room FTS rebuild support and search coverage for phone/email/address
- Added unit tests for keyword ranking
- Updated the real-device test guide and import script

## Current state

- The current embedding runtime still expects an on-device embedding model that the app can load locally.
- The app no longer needs the custom `embeddinggemma_quant` naming.
- The current branch now points to the official EmbeddingGemma naming:
  - `embeddinggemma-300m.tflite`
  - `embeddinggemma-300m.task`
- I downloaded the official Hugging Face repo files for `google/embeddinggemma-300m` into:
  - `models/embeddinggemma-300m/`

## Important finding

- The downloaded Hugging Face files are the original checkpoint files, not a mobile-ready quantized model.
- `model.safetensors` is about 1.21 GB and is too heavy for the intended mobile workflow.
- The model card shows the repo contains many quantized variants, so the next step is to pick a quantized version, not use the raw checkpoint.

## What still needs to happen

- ~~Choose a quantized EmbeddingGemma variant suitable for mobile~~ Done: `litert-community/embeddinggemma-300m`, `embeddinggemma-300M_seq256_mixed-precision.tflite` (generic, no chipset suffix), renamed to `embeddinggemma-300m.tflite`
- Update the app runtime to match the chosen model format
- ~~Keep `functiongemma_270m.litertlm` unchanged unless the LLM path changes later~~ — the LLM path did change: split into two roles (see below)

## LLM role split (2026-07-10)

FunctionGemma 270M is explicitly documented as "not intended for use as a direct dialogue model" — it is a tool-calling specialist, not a general chat/RAG model. The chat tab's answer generation was reusing it anyway, which hurt RAG answer quality. Split into two roles in `LiteRtLmChatEngine` (`LlmRole` enum):

- `LlmRole.ToolCalling` → `functiongemma_270m.litertlm` — unchanged, for future ReAct tool-call dispatch
- `LlmRole.Chat` → `gemma3-1b-it-int4.litertlm` (new) — used by `runChat` in `MainActivity.kt` for RAG answer generation

`gemma3-1b-it-int4.litertlm` comes from the gated `litert-community/Gemma3-1B-IT` Hugging Face repo (generic dynamic_int4 QAT build, 529MB, no chipset suffix) — access request pending as of this note.

`ModelsScreen` now manages 3 models (embedding / Tool LLM / Chat LLM) with separate status panels, import buttons, and smoke-test buttons.

## Notes

- Do not merge or touch `main`.
- Keep all future work on the feature branch only.
