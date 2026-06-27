# sidecar-info

Design notes, diagrams, and benchmark reports for Dynamo sidecars that drive
native engines over OpenEngine.

## Start here

| Document | Purpose |
|---|---|
| [Implementation brief](implementation_brief.md) | Architecture and ownership |
| [OpenEngine API](openengine_api.md) | Links to the canonical protocol docs |
| [SGLang](sglang/) | Adoption guide, diagrams, and benchmarks |
| [vLLM](vllm/) | Implementation notes, diagrams, and benchmarks |
| [DSV4 Pro GB200 findings](sglang/benchmarks/benchmark_inferencex_dsv4_pro_gb200_sidecar_findings_2026-06-26.md) | Non-MTP sidecar comparison with public InferenceX results |

## Diagrams

| Flow | Source | Rendered |
|---|---|---|
| Aggregated request | [Mermaid](diagrams/agg_request.mmd) | [PNG](diagrams/agg_request.png) |
| Cancellation | [Mermaid](diagrams/request_cancellation.mmd) | [PNG](diagrams/request_cancellation.png) |
| Migration | [Mermaid](diagrams/request_migration.mmd) | [PNG](diagrams/request_migration.png) |
| SGLang disaggregation | [Mermaid](sglang/diagrams/disagg_request.mmd) | [PNG](sglang/diagrams/disagg_request.png) |
| vLLM disaggregation | [Mermaid](vllm/diagrams/disagg_request.mmd) | [PNG](vllm/diagrams/disagg_request.png) |
| vLLM encode/prefill/decode | [Mermaid](vllm/diagrams/epd_request.mmd) | [PNG](vllm/diagrams/epd_request.png) |

Edit Mermaid sources and re-render the matching PNG assets.
