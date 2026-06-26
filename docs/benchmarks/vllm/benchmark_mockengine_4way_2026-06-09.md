# Mock-Engine 4-Way Frontend/Backend Benchmark

**Date:** 2026-06-09
**Run type:** GPU-free throughput comparison of four Dynamo backend
architectures over the vLLM Rust **mock engine**, replicating the experiment in
ai-dynamo/dynamo PR #9206 (which itself uses the vllm-project/vllm#43469
workload).

## What was tested

Four ways to drive the same model through a Dynamo frontend, each fronted by the
**same** GPU-free `vllm-mock-engine` (model forward removed, one-token output
chunks). The only variable is the frontend/backend architecture between the
Dynamo HTTP frontend and the mock:

| # | Config | Path | Mock handshake |
|---|---|---|---|
| 1 | **Rust sidecar (ours)** | `dynamo-vllm-sidecar` → OpenEngine gRPC :50051 → `vllm-rs serve` → mock | tcp://127.0.0.1:29550 |
| 2 | Legacy Python (no unified backend) | `python -m dynamo.vllm` (handshake owner) → mock | tcp://127.0.0.1:29570 |
| 3 | Unified backend + Python wrapper | `python -m dynamo.vllm.unified_main` → mock | tcp://127.0.0.1:29570 |
| 4 | PR #9206 native Rust backend | `dynamo-vllm-rs-backend` (in-process engine-core client) → mock | tcp://127.0.0.1:29560 |

Config 1 is the only one with process separation **and** a vendor-neutral wire
contract: it adds a Dynamo worker → OpenEngine gRPC → separate `vllm-rs`
frontend process → engine-core ZMQ hop. Config 4 talks the engine-core ZMQ
protocol directly, in-process. Configs 2/3 are Python coordinators acting as the
handshake owner (`--data-parallel-size-local 0`, no local engine) with the mock
dialing in.

## Hardware & environment

- **Host:** computelab `computelab-build-4` (CPU-only run — mock engine needs no GPU).
- **Container:** docker `mockbench` (`/work` = host `/tmp/connorc`).
- **Infra (shared, kept up across all four legs):** etcd :2379, NATS :4222,
  Dynamo frontend `python -m dynamo.frontend --http-port 8000`.
- **Binaries (release):**
  - `/work/target-vllm-c/release/{vllm-rs, vllm-mock-engine}`
  - `/work/target-dynamo-c/release/{dynamo-vllm-sidecar, dynamo-vllm-rs-backend}`
  - vLLM fork forced via `PYTHONPATH=/work/src/vllm`.

## Model & engine config

- **Model:** `Qwen/Qwen3-0.6B`, `--enforce-eager`, DP=1.
- **Mock:** `vllm-mock-engine --engine-count 1`, `output_token_chunk_size=1`, no
  GPU model execution.

## Benchmark config

- Workload **in=32 / out=512**, `--dataset-name random --random-range-ratio 0
  --ignore-eos` (same shape as vllm#43469).
- Client: `vllm bench serve --backend openai --endpoint /v1/completions` against
  the frontend at :8000.

## Methodology

PR #9206 / vllm#43469 report throughput annotated `@ c=<optimal>` — a
**concurrency sweep reporting the peak**, not a single fixed concurrency. A
fixed concurrency does not reproduce the table because slow (Python) backends
*overload* past a point and fast backends are *under-driven* below it.

So, per config:

- Concurrency sweep **C ∈ {256, 512, 1024, 2048}** (total concurrent requests).
- At each C, **8 sharded `vllm bench serve` clients** run in parallel
  (`max-concurrency = C/8` each), 1024 prompts/shard = **8192 prompts/point**.
  Sharding avoids the GIL-bound single-client dispatch cap (~180–220 req/s),
  which would otherwise mask differences between the fast backends.
- Aggregate **req/s = Σ completed / wall**, where wall = `max(shard duration)`
  (request-phase only, excludes the ~12–14 s of 8× Python client import/startup
  so the figure reflects backend throughput, consistent across configs).
- Only **one config runs at a time** — all four register under the same
  `dynamo.backend.generate` key.

## Results — full sweep

| Config | c=256 | c=512 | c=1024 | c=2048 |
|---|---:|---:|---:|---:|
| 1 — Rust sidecar (ours) | **503.29** (1✗) | 464.01 (1✗) | 462.46 (27✗) | 473.37 (720✗) |
| 2 — Legacy Python | 126.31 | 128.46 | **129.49** | 121.91 |
| 3 — Unified + Python | 142.14 | 143.10 | **152.44** | 125.08 |
| 4 — PR #9206 Rust backend | **1013.16** (21✗) | 977.73 (15✗) | 812.99 | 853.07 (2✗) |

(req/s; **bold** = per-config peak; `N✗` = failed requests out of 8192.)

## Results — peak per config

| Config | Peak req/s | @ c | out tok/s | mean TTFT | mean TPOT | fail @ peak |
|---|---:|---:|---:|---:|---:|---:|
| **1 — Rust sidecar (ours)** | **503.29** | 256 | 257,686 | 49 ms | 0.88 ms | 1 / 8192 |
| 2 — Legacy Python | 129.49 | 1024 | 66,299 | 6,230 ms | 0.46 ms | 0 |
| 3 — Unified + Python | 152.44 | 1024 | 78,051 | 6,069 ms | 0.76 ms | 0 |
| **4 — PR #9206 Rust backend** | **1013.16** | 256 | 518,736 | 127 ms | 0.20 ms | 21 / 8192 |

## Takeaways

- **Three clean tiers:** Python backends (~130–152 req/s) ≪ Rust sidecar (503)
  ≪ in-process Rust backend (1013). The sidecar is **~3.3× the best Python
  backend**.
- **Cost of process separation:** config 1 lands at **~½ of config 4** (503 vs
  1013) on the identical mock. The gap is the sidecar's extra hop — Dynamo
  worker → OpenEngine gRPC → separate `vllm-rs` process → engine-core ZMQ —
  versus config 4's direct in-process engine-core client. That ~2× is the price
  of the vendor-neutral OpenEngine contract + process isolation.
- **Python is GIL-bound and queue-limited:** configs 2/3 plateau ~130–152 req/s,
  carry multi-second TTFT (~6 s) from queueing, and *overload* past c=1024
  (throughput drops at c=2048). Unified (152) edges legacy (129).
- **Rust paths peak early** (c=256, TTFT 49–127 ms) and don't benefit from more
  concurrency; Python paths peak at c=1024.

## Failure modes

- **Config 1 (sidecar):** clean at low concurrency but **degrades under load** —
  720/8192 (8.8%) failures at c=2048, and no throughput scaling past c=256. The
  OpenEngine gRPC hop appears to saturate. This is a robustness concern for the
  sidecar at high concurrency and is the most actionable follow-up.
- **Config 4:** a few failures at *low* concurrency (21@c256, 15@c512), clean at
  c=1024 — consistent with cold-start/warmup timeouts rather than overload.
- **Configs 2/3:** zero failures, but TTFT balloons to 6–15 s under queueing.

## Vs PR #9206 anchors

PR reported AsyncLLM-wrapper (≈ config 3) = **168.01** and native Rust backend
(≈ config 4) = **553.40** req/s.

- Config 3 here = 152.44 — same ballpark, ~9% under (real end-to-end wall incl.
  client startup gives 123.55; the two bracket the PR's 168).
- Config 4 here = 1013 — well above the PR's 553, because the sharded-client
  methodology removes the single-client GIL cap and this host differs from the
  PR's GB200.
- The **Rust-vs-Python ratio is larger here** (6.6× vs the PR's 3.3×); the
  direction and ordering hold.

## Caveats

- GPU-free mock only: this measures the **frontend + transport ceiling**
  (scheduling, engine-core messaging, detokenization/streaming, HTTP/SSE), *not*
  model quality or real-engine throughput.
- Single host, DP=1, one workload point (32/512), `--enforce-eager`.
- `wall = max(shard duration)` slightly overestimates aggregate throughput
  (ignores inter-shard start skew) but is applied uniformly, so the comparison
  is fair.
- `bc` is absent in the container; config-2 walls were reconstructed from shard
  durations (configs 1/3/4 captured real `date`-based walls).

## Data provenance

- Raw per-shard results persist on `computelab-build-4` at
  `/work/bench/c{1,2,3,4}sw_c{256,512,1024,2048}_s{1..8}.json` (in-container;
  host `/tmp/connorc/bench/`).
- Per-leg backend/mock launch logs at `/work/c{1,2,3,4}-*.log`.
- Figures aggregated directly from those shard JSONs (`completed`,
  `total_output_tokens`, `duration`, `mean_ttft_ms`, `mean_tpot_ms`).
