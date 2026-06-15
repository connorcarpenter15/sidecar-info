# sidecar-info

Design docs, request-sequence diagrams, and benchmark reports for the
**sidecar integration for Dynamo over OpenEngine** — a native engine process
runs the model while a separate Dynamo worker drives it over the vendor-neutral
**OpenEngine v1 gRPC contract**. Two engines implement this shape: **vLLM** and
**SGLang**. This repo is the **docs home** — it holds no code (implementation
lives in the Dynamo / vLLM / SGLang forks).

## Layout — engine-isolated

Engine-neutral material lives at the top level; everything engine-specific lives
under `vllm/` or `sglang/` (and `benchmarks/<engine>/`).

| Path | What it is |
|---|---|
| [`implementation_brief.md`](./implementation_brief.md) | Architecture, scope, and what the sidecar should look like. Start here. (neutral) |
| [`openengine_api.md`](./openengine_api.md) | The OpenEngine v1 API spec — the canonical `.proto` contract. (neutral) |
| `agg_request.mmd`, `request_cancellation.mmd`, `request_migration.mmd` | Neutral request-sequence diagrams (same flow for both engines); rendered in [`assets/`](./assets). |
| [`vllm/`](./vllm) | vLLM-specific docs + diagrams (`multimodal_support.md`, `kvbm_support.md`, `disagg_request_vllm.mmd`, `epd_request_vllm.mmd`). |
| [`sglang/`](./sglang) | SGLang-specific docs + diagrams (`disagg_request_sglang.mmd`). |
| [`benchmarks/vllm/`](./benchmarks/vllm) | vLLM-sidecar benchmark reports. |
| [`benchmarks/sglang/`](./benchmarks/sglang) | SGLang-sidecar benchmark reports. |

## Diagrams

| Sequence | Source | Rendered |
|---|---|---|
| Aggregated request (neutral) | [`agg_request.mmd`](./agg_request.mmd) | [`assets/agg_request.png`](./assets/agg_request.png) |
| Request cancellation (neutral) | [`request_cancellation.mmd`](./request_cancellation.mmd) | [`assets/request_cancellation.png`](./assets/request_cancellation.png) |
| Request migration (neutral) | [`request_migration.mmd`](./request_migration.mmd) | [`assets/request_migration.png`](./assets/request_migration.png) |
| Disaggregated request (vLLM) | [`vllm/disagg_request_vllm.mmd`](./vllm/disagg_request_vllm.mmd) | [`vllm/assets/disagg_request_vllm.png`](./vllm/assets/disagg_request_vllm.png) |
| Encode/Prefill/Decode (vLLM) | [`vllm/epd_request_vllm.mmd`](./vllm/epd_request_vllm.mmd) | [`vllm/assets/epd_request_vllm.png`](./vllm/assets/epd_request_vllm.png) |
| Disaggregated request (SGLang) | [`sglang/disagg_request_sglang.mmd`](./sglang/disagg_request_sglang.mmd) | [`sglang/assets/disagg_request_sglang.png`](./sglang/assets/disagg_request_sglang.png) |

Edit the `.mmd` source, then re-render to the matching `assets/*.png`.

## Benchmarks

Dated, self-contained reports (hardware, model/engine config, methodology,
results, takeaways, provenance), split by engine:

- [`benchmarks/vllm/`](./benchmarks/vllm) — real-engine A/Bs (H100 agg, GB300
  disagg, GB300 KV-routing), the GPU-free mock-engine ceiling, and the Track A/B
  4-way sweeps across the compute-regime arc.
- [`benchmarks/sglang/`](./benchmarks/sglang) — SGLang-sidecar reports.

Naming: `benchmark_<platform-or-track>_<scenario>_<date>.md`.
