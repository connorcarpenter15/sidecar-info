# sidecar-info

Design docs, request-sequence diagrams, and benchmark reports for the **vLLM
sidecar integration for Dynamo over OpenEngine**.

A native vLLM engine process runs the model; a separate Dynamo worker drives it
over the vendor-neutral **OpenEngine v1 gRPC contract** (the same
process-separation shape as the SGLang sidecar, but engine-agnostic). This repo
is the **docs home** — it holds no code. Implementation lives in the Dynamo and
vLLM forks.

## Contents

| Path | What it is |
|---|---|
| [`implementation_brief.md`](./implementation_brief.md) | The implementation brief: architecture, scope, and what the sidecar should look like. Start here. |
| [`openengine_api.md`](./openengine_api.md) | The OpenEngine v1 API spec — the canonical `.proto` contract (Generate, model/load metadata, health, lifecycle, disagg, KV events). |
| `*.mmd` | Editable Mermaid sources for the request-sequence diagrams. |
| [`assets/`](./assets) | Rendered `.png` of each diagram. |
| [`benchmarks/`](./benchmarks) | Dated benchmark reports (`benchmark_<platform>_<scenario>_<date>.md`). |

## Diagrams

| Sequence | Source | Rendered |
|---|---|---|
| Aggregated request | [`agg_request.mmd`](./agg_request.mmd) | [`assets/agg_request.png`](./assets/agg_request.png) |
| Disaggregated request (vLLM) | [`disagg_request_vllm.mmd`](./disagg_request_vllm.mmd) | [`assets/disagg_request_vllm.png`](./assets/disagg_request_vllm.png) |
| Disaggregated request (SGLang) | [`disagg_request_sglang.mmd`](./disagg_request_sglang.mmd) | [`assets/disagg_request_sglang.png`](./assets/disagg_request_sglang.png) |
| Request cancellation | [`request_cancellation.mmd`](./request_cancellation.mmd) | [`assets/request_cancellation.png`](./assets/request_cancellation.png) |
| Request migration | [`request_migration.mmd`](./request_migration.mmd) | [`assets/request_migration.png`](./assets/request_migration.png) |

Edit the `.mmd` source, then re-render to the matching `assets/*.png`.

## Benchmarks

Reports under [`benchmarks/`](./benchmarks) cover both real-engine A/Bs (H100
agg, GB300 disagg, GB300 KV-routing) and GPU-free frontend/transport ceilings
(mock-engine). Each is a self-contained, dated record: hardware, model/engine
config, methodology, results table, takeaways, and data provenance.
