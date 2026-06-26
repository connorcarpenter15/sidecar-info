# sidecar-info

Design notes, diagrams, and benchmark reports for Dynamo sidecars that drive
native engines over OpenEngine.

## Start here

| Document | Purpose |
|---|---|
| [Implementation brief](docs/implementation_brief.md) | Architecture and ownership |
| [OpenEngine API](docs/openengine_api.md) | Links to the canonical protocol docs |
| [SGLang adoption](docs/sglang/openengine_adoption.md) | Native SGLang and Dynamo sidecar boundary |
| [vLLM notes](docs/vllm/) | Multimodal, KVBM, migration, and request flows |
| [Benchmarks](docs/benchmarks/) | Dated vLLM and SGLang reports |

## Diagrams

| Flow | Source | Rendered |
|---|---|---|
| Aggregated request | [Mermaid](docs/diagrams/agg_request.mmd) | [PNG](docs/diagrams/assets/agg_request.png) |
| Cancellation | [Mermaid](docs/diagrams/request_cancellation.mmd) | [PNG](docs/diagrams/assets/request_cancellation.png) |
| Migration | [Mermaid](docs/diagrams/request_migration.mmd) | [PNG](docs/diagrams/assets/request_migration.png) |
| SGLang disaggregation | [Mermaid](docs/sglang/disagg_request_sglang.mmd) | [PNG](docs/sglang/assets/disagg_request_sglang.png) |
| vLLM disaggregation | [Mermaid](docs/vllm/disagg_request_vllm.mmd) | [PNG](docs/vllm/assets/disagg_request_vllm.png) |
| vLLM encode/prefill/decode | [Mermaid](docs/vllm/epd_request_vllm.mmd) | [PNG](docs/vllm/assets/epd_request_vllm.png) |

Edit Mermaid sources and re-render the matching PNG assets.
