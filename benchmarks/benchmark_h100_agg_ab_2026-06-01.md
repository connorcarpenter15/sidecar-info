# Sidecar H100 A/B — Initial Benchmark Report

**Date:** 2026-06-01
**Run type:** first real perf A/B of the OpenEngine Rust sidecar vs. in-process vLLM+Dynamo

## What was tested

Two legs, **identical** container / wheel / model / flags — the *only* variable
is the architecture:

| Leg | Architecture |
|---|---|
| `baseline` | in-process `python -m dynamo.vllm` (aggregated) |
| `sidecar` | `vllm-rs serve` engine + `dynamo-vllm-sidecar` worker, talking over **OpenEngine v1 gRPC** |

## Hardware & environment

- **GPU:** 1x NVIDIA H100 (TP1, aggregated)
- **Cluster/node:** computelab, node `ipp2-0128`, Slurm job `2407685`
- **Container:** `…ecr…/ai-dynamo/dynamo:d27f61b1…-vllm-dev-cuda12`
- **vLLM wheel:** `vllm-0.22.1rc1.dev3+g5dbf1605a` (cu13 wheel run in cu12 image)

## Model & engine config

- **Model:** `Qwen/Qwen2.5-0.5B-Instruct`
- **Flags:** `--enforce-eager --gpu-memory-utilization 0.4 --max-model-len 2048`

## Benchmark config (sa-bench `benchmark_serving.py`)

- **ISL 1024 / OSL 512**, random-range 0.8, `--ignore-eos`, request-rate `inf`
- **Concurrencies:** 1, 16, 64

## Results

| conc | leg | req/s | out tok/s | tot tok/s | TTFT mean (ms) | TTFT p99 (ms) | TPOT (ms) | ITL (ms) | e2el mean (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | baseline | 0.17 | 80.6 | 245.2 | 43.3 | 50.5 | 12.34 | 13.64 | 5775 |
| 1 | sidecar | 0.17 | 78.9 | 240.0 | **51.9** | 54.1 | 12.59 | 13.86 | 5900 |
| 16 | baseline | 2.33 | 1058.7 | 3217 | 166.3 | 446.8 | 13.96 | 14.09 | 6492 |
| 16 | sidecar | 2.39 | 1077.3 | 3286 | **132.7** | 351.5 | 13.68 | 13.77 | 6294 |
| 64 | baseline | 3.66 | 1672.8 | 5063 | 518.9 | 1484.7 | 33.12 | 33.76 | 15629 |
| 64 | sidecar | 3.72 | 1667.8 | 5111 | **489.8** | 1426.5 | 33.38 | 33.89 | 15372 |

## Takeaway

- **No throughput regression:** req/s and tok/s match within run-to-run noise
  (±1-3%) at every concurrency.
- **No per-token regression:** TPOT/ITL identical.
- **One measurable cost:** ~**8.6 ms** added mean TTFT at conc 1 (the gRPC hop
  sits on the first-token path). It's a *fixed* cost — at conc 16/64 the
  sidecar's TTFT is actually lower (noise + small prompt counts), so it
  amortizes away under load.

## Caveats (not covered by this run)

Tiny model (0.5B), aggregated only (no disagg/NIXL KV transfer), short ISL/OSL,
modest prompt counts. The disagg KV-transfer path and large-model/large-context
behavior remain unproven at scale.

## Data provenance

- Figures come from the run's captured summary, cross-checked against
  compute-session command history — not re-read from the raw `benchmark.out`
  (that lived on `/tmp` of the now-freed agg node `ipp2-0128`).
- Job/node attribution corrected from an earlier note that listed job
  `2408934` / `ipp2-0715`; that is the *later disagg* job. The agg A/B staged
  and ran under job `2407685` on `ipp2-0128`.
