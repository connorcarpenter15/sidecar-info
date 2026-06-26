# Multimodal support in the vLLM sidecar

Status of multimodal serving through the vLLM **sidecar** (Dynamo over
OpenEngine), and an analysis of which feature-parity gaps the sidecar
architecture can close cheaply versus which ones the process topology itself
makes expensive.

Companion to [`implementation_brief.md`](../implementation_brief.md) (overall
architecture) and [`openengine_api.md`](../openengine_api.md) (the wire
contract, including the `media` / `MediaItem` / `Modality` additions).

---

## TL;DR

| Capability | Sidecar status | Parity with in-process Dynamo+vLLM |
|---|---|---|
| **Image** — aggregated | ✅ validated e2e | full |
| **Image** — P/D disaggregated | ✅ validated e2e | full (no new transfer code) |
| **Video / audio** — agg or P/D | ❌ not supported | **architectural gap** (see below) |
| Models whose image marker is not a single real vocab token (Qwen-VL) | ❌ rejected at engine load | shared frontend limitation, not sidecar-specific |
| `mm_processor_kwargs` (fps, `use_audio_in_video`, …) | ❌ dropped | needed for omni/video |
| Encoder disaggregation (EPD) | ⛔ out of scope | intentionally not in OpenEngine v1 |
| Pre-decoded / RDMA media descriptors | ⛔ rejected fail-closed | by design — sidecar has no NIXL agent |

Images reach **full** parity, **including P/D**. Everything else is blocked,
and the blockers are *not* in sidecar-specific code — they live in the shared
vLLM Rust frontend and the process split between it and the headless engine.

---

## Architecture recap (why the gaps land where they do)

The sidecar deployment runs **four** cooperating processes:

```
Dynamo frontend ──HTTP/OpenAI──► Dynamo sidecar worker (dynamo-vllm-sidecar)
                                          │  OpenEngine v1 gRPC
                                          ▼
                                 vllm-rs serve  ── the Rust "P0" frontend
                                 (tokenize, chat template, MEDIA PREPROCESS)
                                          │  engine-core ZMQ (msgpack)
                                          ▼
                                 headless Python EngineCore ("P1")
                                 (scheduler + model executor on the GPU)
```

The P0/P1 split is **vLLM's own** design, not the sidecar's. vLLM shipped a
Rust frontend (`vllm-rs serve`) that replaces the Python `AsyncLLM` frontend:
it owns tokenization, chat-template rendering, and **multimodal
preprocessing**, then hands msgpack'd `EngineCoreRequest`s to a headless
Python `EngineCore` over ZMQ. The "sidecar" boundary is the OpenEngine gRPC
hop *above* the Rust frontend — the Dynamo worker imports no torch/NIXL and
has no GPU.

The consequence that drives every gap below: **media preprocessing happens in
the Rust frontend, not on the GPU engine.** Whatever the Rust frontend cannot
preprocess cannot be served, because the headless engine downstream never runs
the Python preprocessing path.

---

## What works today: image (agg + P/D)

The image path reuses the Rust frontend's *existing* image→`MmFeatures`
pipeline rather than duplicating it. End to end:

1. **Frontend → sidecar (URL passthrough).** The sidecar's model card has
   `media_decoder = None`, so the Dynamo preprocessor takes the URL-passthrough
   branch and forwards the raw `image_url.url` (http(s) **or** `data:base64`)
   as `MultimodalData::Url`. The worker-bound token_ids carry the
   *un-expanded* placeholder marker (one per image) — expansion is the
   engine's job.
2. **Sidecar → proto.** `build_generate_request` (`dynamo/lib/vllm-sidecar/src/engine.rs`)
   maps each `MultimodalData` into a `MediaItem` on the new `media` field —
   `data_uri` when the string starts with `data:`, else `url`. A
   `MultimodalData::Decoded` (RDMA descriptor) is **rejected fail-closed**: the
   sidecar has no NIXL agent to dereference it.
3. **Proto.** `GenerateRequest.media = 8` (repeated `MediaItem`), plus the
   `Modality` enum and `MediaItem` message. Order is significant: the i-th
   media item aligns with the i-th placeholder marker. See
   [`openengine_api.md`](../openengine_api.md).
4. **vLLM OpenEngine server.** `media_parts_from_request`
   (`vllm/rust/src/server/src/grpc/openengine/convert.rs`) turns proto media
   into chat `MediaContentPart`s (image only; video/audio → `Unimplemented`;
   missing source → `InvalidArgument`). `generate`
   (`.../openengine/mod.rs`) then calls `ChatLlm::prepare_media`, which fetches
   + preprocesses the media, expands the placeholder markers in `token_ids` in
   place, and attaches `MmFeatures` — **before** `mark_prefill_request`.
   `get_model_info` now reports the real `supports_multimodal()`.
5. **Engine.** `MmFeatures` ride the existing msgpack `EngineCoreRequest` to
   the headless engine, which prefills with the vision encoder in-process.

**P/D needs zero new transfer code.** The vision encoder runs *inside* the
prefill engine; the produced KV moves to decode over vLLM's existing
`NixlConnector`, exactly as text P/D does — the sidecar only relays the opaque
`kv_session` handoff. Media only has to reach the **prefill** engine; decode
needs token_ids + the KV session, no media.

Validated e2e on `llava-hf/llava-1.5-7b-hf` (computelab H100), both
aggregated and P/D, exercising both media paths (http URL and `data:` URI).
Launch scripts: `dynamo/examples/backends/vllm/launch/sidecar_agg_multimodal.sh`
and `sidecar_disagg_multimodal_p_d.sh` (set `DYN_REQUEST_PLANE=tcp` — base64
images exceed the 1 MB NATS limit).

---

## The parity gaps

### 1. Video / audio — the one true architectural gap

**Symptom.** `media_parts_from_request` rejects `MODALITY_VIDEO` / `MODALITY_AUDIO`
with `Unimplemented`. There is no path to serve them today.

**Root cause is the P0/P1 split, not missing wiring.** Two facts combine:

- The Rust frontend's media preprocessing is **image-only**. It is built on the
  external `llm-multimodal` crate (a frozen git pin), and
  `vllm/rust/src/chat/src/multimodal.rs` uses only `ImagePreProcessor` /
  `ImageProcessorRegistry` / `PreprocessedImages`. The crate *names*
  `Audio`/`Video` modalities but implements no processors for them, and the
  chat layer handles `Modality::Image` only. Adding video/audio here means
  porting model-specific preprocessing (video frame sampling + grid, audio
  decode + resample, per-modality placeholder expansion) into Rust — net-new
  work, much of it upstream.

- The headless Python engine **cannot** pick up the slack. vLLM's full Python
  multimodal preprocessing lives in `InputProcessor.process_inputs`
  (`vllm/vllm/v1/engine/input_processor.py:242`), which dispatches into the
  modality-specific processors registered in `MULTIMODAL_REGISTRY` (audio and
  video included). But that processor is owned by the Python frontend
  `AsyncLLM` (`vllm/vllm/v1/engine/async_llm.py:135`). In the sidecar stack the
  frontend is the **Rust** `vllm-rs serve`, so `AsyncLLM` is never started.
  `run_headless` (`vllm/vllm/entrypoints/cli/serve.py:173`) spins up only a
  `CoreEngineProcManager` → `EngineCore`. `EngineCore` touches
  `MULTIMODAL_REGISTRY` for the receiver **cache** only
  (`vllm/vllm/v1/engine/core.py:191`); it never runs `process_inputs`.

So the modality reaches a wall on both sides: the Rust frontend can't
preprocess audio/video, and the only process that could (the Python
`InputProcessor`) isn't running anywhere in the sidecar topology. This is a
*wiring/topology* gap, not a model-capability gap — the engine itself can run
these models once it's handed preprocessed `MmFeatures`.

**Paths to close it** (see "Closing the audio/video gap" below).

### 2. Models whose image marker is not a single real vocab token (Qwen-VL)

`MultimodalModelInfo` resolves the placeholder marker by
`tokenizer.token_to_id("<image>")` at backend init
(`vllm/rust/src/chat/src/multimodal.rs`, ~line 106). LLaVA-1.5 has `<image>` as
a real added token (id 32000) → works. Qwen2.5-VL's tokenizer has only
`<|image_pad|>`, no `<image>` → init fails ("placeholder token `<image>` is not
in the tokenizer vocabulary"). This is in the **shared** Rust frontend +
`llm-multimodal` (the spec hardcodes `placeholder_token = "<image>"`), so it
hits native chat too — it is not sidecar-specific. Use a single-marker family
(LLaVA-1.5, or Llama-4 `<|image|>`) until `llm-multimodal` stops hardcoding the
marker.

### 3. `mm_processor_kwargs` dropped

Per-request processor kwargs (`fps`, `use_audio_in_video`, image detail, …) are
not carried over the wire today. Harmless for basic image, but required for
omni/video. Adds a proto field (or `metadata` carriage) plus forwarding in
`build_generate_request` — a dependency of the video/audio work.

### 4. Encoder disaggregation (EPD) — intentionally out of scope

OpenEngine v1 has **no `encode` engine role**, by design. A separate encode
engine shipping encoder-cache embeddings to a prefill engine is the only
multimodal topology that needs a *new* transfer; Dynamo's Python embedding
transfer is GPU/NIXL-bound and not portable to the Rust sidecar, and vLLM's
native EC transfer is disk-based + 1P1D-only. EPD, if ever pursued, is a
separate future effort outside the sidecar v1 scope.

### 5. Pre-decoded / RDMA media — rejected by design

If a deployment registers a `media_decoder`, the Dynamo frontend decodes media
itself and emits a `Decoded(RdmaMediaDataDescriptor)` pointing at GPU/NIXL
memory. The sidecar has no NIXL agent to dereference it, so this is rejected
fail-closed. Sidecar deployments must run in URL-passthrough mode
(`media_decoder: null`). Not a gap — a deliberate constraint of the
process-separated design.

### 6. Request-plane size

Base64 `data:` images exceed the default NATS 1 MB request-plane limit. Set
`DYN_REQUEST_PLANE=tcp`; prefer `url` over `data_uri` where possible. For very
large data URIs or video, a gRPC max-message bump may also be needed.

---

## Closing the audio/video gap

The cheapest correct fix keeps the engine where the Python preprocessing
already lives, instead of re-porting it into Rust.

**Option A (recommended): co-locate a Python `InputProcessor` with the headless
engine and add a "raw media" engine-core message.** When the Rust frontend sees
a non-image modality it can't preprocess, it forwards the raw media + prompt
over a new engine-core wire message; a small Python shim alongside `EngineCore`
runs `InputProcessor.process_inputs` (reusing `MULTIMODAL_REGISTRY`, so every
model vLLM already supports works) and feeds the result into the scheduler.
Pros: reuses all upstream Python preprocessing; no Rust re-implementation per
model. Cons: a new engine-core message + a preprocessing hop on the engine
host; needs `mm_processor_kwargs` carriage (gap #3).

**Option B: port preprocessing into the Rust `llm-multimodal` crate.** Add
video/audio fetch+decode and model-specific processors in Rust, then generalize
`prepare_multimodal` to non-image modalities. Pros: keeps all preprocessing in
the frontend, uniform with image. Cons: large, partly-upstream effort,
re-implements per-model logic that already exists in Python, and the crate is a
frozen external pin.

**Option C: run the full Python frontend (`AsyncLLM`) instead of headless.**
Defeats the purpose of the sidecar (process separation + the Rust frontend),
so not viable for this integration.

Recommendation: **Option A.** It treats audio/video as a routing problem — get
the bytes to the process that already knows how to preprocess them — rather
than a re-implementation problem.

---

## Pointers

| Area | Location |
|---|---|
| Wire contract (media field, `MediaItem`, `Modality`) | `openengine/proto/openengine.proto`; documented in [`openengine_api.md`](../openengine_api.md) |
| Sidecar media mapping + fail-closed on `Decoded` | `dynamo/lib/vllm-sidecar/src/engine.rs` (`build_generate_request`, `build_media`) |
| vLLM proto→chat media conversion | `vllm/rust/src/server/src/grpc/openengine/convert.rs` (`media_parts_from_request`) |
| vLLM generate wiring + `supports_multimodal` | `vllm/rust/src/server/src/grpc/openengine/mod.rs` |
| Image→`MmFeatures` pipeline (image-only) | `vllm/rust/src/chat/src/{lib.rs,multimodal.rs}` (`prepare_media`, `prepare_multimodal`) |
| Python preprocessing the sidecar bypasses | `vllm/vllm/v1/engine/input_processor.py` (`process_inputs`), `async_llm.py` |
| Headless engine entry (no Python frontend) | `vllm/vllm/entrypoints/cli/serve.py` (`run_headless`) |
| Launch scripts | `dynamo/examples/backends/vllm/launch/sidecar_{agg,disagg}_multimodal*.sh` |

**Model prep note.** `llava-hf/llava-1.5-7b-hf` needs two patches before
`vllm-rs serve` will load it on this fork: add the canonical Llama-7B fields to
`config.json`'s `text_config` (the official card omits `num_attention_heads`),
and strip the `{% generation %}`/`{% endgeneration %}` tags from
`chat_template.json` (the fork's minijinja renderer can't parse them). Both are
frontend issues, not sidecar issues.
