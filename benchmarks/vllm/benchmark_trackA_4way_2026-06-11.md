# Track A — Mock-Engine 4-Way Sweep (full shape × DP × concurrency matrix)

**Date:** sweep 2026-06-09/10, config-4 re-run 2026-06-11.
**Run type:** GPU-free throughput/stability comparison of four Dynamo
backend architectures over the vLLM Rust **mock engine** (model forward
removed, one-token output chunks). This is the automated, full-matrix
descendant of the single-shape hand-run in
[`benchmark_mockengine_4way_2026-06-09.md`](benchmark_mockengine_4way_2026-06-09.md),
and the GPU-free counterpart to the real-engine Track B sweep in
[`benchmark_trackB_4way_2026-06-10.md`](benchmark_trackB_4way_2026-06-10.md).

## What was tested

Four ways to drive the same model through **one** shared Dynamo HTTP frontend
(:8000) + etcd (:2379) + NATS (:4222), each fronted by the **same** GPU-free
`vllm-mock-engine`. Only one config runs at a time; all four register under
`dynamo.backend.generate`. The only variable is the frontend/backend
architecture between the Dynamo frontend and the mock:

| # | Config | Path |
|---|--------|------|
| 1 | **Rust sidecar (ours)** | `dynamo-vllm-sidecar` → OpenEngine gRPC :50051 → `vllm-rs serve` → mock |
| 2 | Legacy Python | `python -m dynamo.vllm` (handshake owner) → mock |
| 3 | Unified Python | `python -m dynamo.vllm.unified_main` → mock |
| 4 | PR #9206 native Rust backend | `dynamo-vllm-rs-backend` (in-process engine-core client) → mock |

Config 1 is the only one with process separation **and** a vendor-neutral wire
contract (Dynamo worker → OpenEngine gRPC → separate `vllm-rs` process →
engine-core ZMQ). Config 4 talks engine-core ZMQ directly, in-process. Configs
2/3 are Python coordinators acting as handshake owner (`--data-parallel-size-local 0`).

## Hardware & environment

- **Host:** computelab `computelab-build-4` (CPU-only — the mock needs no GPU).
- **Container:** docker `mockbench`, host-networked (`/work` = host `/tmp/connorc`).
- **Infra (shared):** etcd :2379, NATS :4222, Dynamo frontend
  `python -m dynamo.frontend --http-port 8000`.
- **Binaries (release):** `/work/target-vllm-c/release/{vllm-rs,vllm-mock-engine}`,
  `/work/target-dynamo-c/release/{dynamo-vllm-sidecar,dynamo-vllm-rs-backend}`.

## Model & benchmark config

- **Model:** `Qwen/Qwen3-0.6B`, `--enforce-eager` (all four configs).
- **Mock:** `vllm-mock-engine`, `output_token_chunk_size=1`, no GPU model exec.
- **Matrix:** 4 shapes {`32x512`, `1024x1024`, `4096x256`, `8192x1024`} ×
  DP {1, 4} × concurrency C {1, 16, 64, 256, 512, 1024, 2048, 4096}.
- **Sharded clients:** configs 1 & 4 use 12 shards, configs 2 & 3 use 8;
  per-shard prompts = 128 for C∈{1,16,64} else 1024 (sharding removes the
  single-client GIL dispatch cap so it doesn't mask the fast backends).
- **Aggregate req/s** = Σ completed / `max(shard wall)`; request-phase only.

## Results — peak per config (clean points, fail < 1%)

| Config | Peak req/s | @ (shape, DP, conc) | Peak out_tok/s | @ (shape, DP, conc) |
|--------|-----------:|---------------------|---------------:|---------------------|
| **4 — native Rust** | **1204.5** | 32x512, DP1, c256 | **659,003** | 1024x1024, DP1, c256 |
| **1 — Rust sidecar (ours)** | **1068.2** | 4096x256, DP4, c2048 | **449,387** | 1024x1024, DP4, c64 |
| 3 — unified Python | 221.5 | 4096x256, DP1, c2048 | 78,437 | 1024x1024, DP1, c256 |
| 2 — legacy Python | 172.0 | 4096x256, DP1, c2048 | 69,052 | 1024x1024, DP1, c256 |

The two Rust frontends are **~5× faster on req/s** and **~6–9× faster on
out_tok/s** than the best Python coordinator. (Config 1 also hits 1084.4 req/s
@ 4096x256/DP4/c256 at 1.02% fail, just over the clean threshold; config 4 hits
1190.1 @ 32x512/DP4/c2048 at 0.07%.)

## Results — iso-point head-to-head (DP4; req/s, fail%)

**4096x256** (short output — fewest per-token streaming hops):

| conc | c1 sidecar | c2 legacy | c3 unified | c4 native |
|------|-----------:|----------:|-----------:|----------:|
| c256 | 1084.4 (1.02%) | 77.8 (0%) | 107.0 (0%) | 924.7 (0.33%) |
| c1024 | 1065.0 (0.20%) | 82.6 (0%) | 98.5 (0%) | 990.5 (0.24%) |
| c2048 | **1068.2 (0.08%)** | 82.2 (0%) | 97.7 (0%) | 1012.3 (0.25%) |
| c4096 | 642.5 (4.95%) | 85.7 (0%) | 103.7 (0%) | 958.4 (0.09%) |

**32x512** (sidecar plateaus; native scales with concurrency):

| conc | c1 sidecar | c2 legacy | c3 unified | c4 native |
|------|-----------:|----------:|-----------:|----------:|
| c64 | 778.2 (0.78%) | 65.8 (0%) | 80.7 (0%) | 730.4 (0.85%) |
| c1024 | 508.2 (0.51%) | 81.1 (0%) | 107.3 (0%) | 989.8 (0.02%) |
| c2048 | 518.0 (0.04%) | 80.6 (0%) | 112.9 (0%) | **1190.1 (0.07%)** |
| c4096 | 594.7 (7.15%) | 79.3 (0%) | 122.3 (0%) | 1144.3 (0.11%) |

**8192x1024** (heaviest — long input + long output; the sidecar stability cliff):

| conc | c1 sidecar | c2 legacy | c3 unified | c4 native |
|------|-----------:|----------:|-----------:|----------:|
| c256 | 360.3 (0.55%) | 36.4 (0%) | 37.9 (0%) | 302.6 (0.74%) |
| c1024 | 298.7 (0.20%) | 30.6 (0%) | 38.1 (0%) | 347.4 (0.28%) |
| c2048 | 253.2 (4.39%) | 37.1 (0%) | 39.9 (0%) | 354.0 (0.28%) |
| c4096 | 245.4 (**29.39%**) | 37.0 (0%) | — (frontend death†) | 368.6 (**0.36%**) |

†`c3_dp4_8192x1024_c4096` shows 100% fail in the original `agg.csv` — that is
the point at which the shared frontend crashed (see *Frontend-death incident*),
not a config-3 backend failure.

## Headline findings

1. **Two tiers, split by language.** Rust frontends (c1 sidecar, c4 native) hit
   ~1000–1200 req/s and ~450–660K out_tok/s; Python coordinators (c2, c3) top
   out at ~170–220 req/s and ~70–78K out_tok/s. With zero model compute the
   workload is *pure framework + transport overhead*, and the Python coordinators
   are GIL/queue-bound (~5–8× behind). Confirms the 2026-06-09 hand-run across
   the full matrix.

2. **Within the Rust tier, native (c4) ≥ sidecar (c1) on both throughput AND
   stability — the OPPOSITE of Track B3.** c4 peaks higher (1204 vs 1068 req/s;
   659K vs 449K out_tok/s) and, decisively, **stays clean at the extreme stress
   point** (8192x1024/DP4/c4096: 0.36% fail vs the sidecar's 29.39%). The
   sidecar's OpenEngine gRPC hop is *per output token*: on short-output shapes
   (4096x256, out=256) it is competitive-to-leading and scales to c2048
   (c1 1068 ≥ c4 1012 at c2048); on long-output + extreme-concurrency shapes
   the hop saturates and the sidecar drops up to ~30% of requests, while the
   in-process native backend (no hop) absorbs the burst.

3. **Python is bulletproof but slow.** Configs 2/3 had **0% fail at every
   point** (the single 100% row is the frontend-crash artifact, not a backend
   failure). The GIL serializes dispatch so they never overload the transport —
   they trade throughput for stability and cap at ~170–220 req/s with
   multi-second TTFT under queueing.

4. **The sidecar peaks early then plateaus; native scales with concurrency.**
   On 32x512 the sidecar tops out ~c64 (778 req/s) and stays ~500–600 through
   c4096, whereas native climbs to 1190 @ c2048. The gRPC hop caps the sidecar's
   concurrency scaling in the GPU-free regime.

## Why Track A and Track B disagree on the sidecar

Same mechanism — *per-token gRPC-hop amortization* — opposite outcome, because
the variable that flips is **per-token engine compute**:

- **Track B (real engine):** at moderate-to-high per-token compute the engine
  work dominates wall time, so the per-token OpenEngine hop is amortized; the
  Rust frontend's efficient detok/sampling surfaces and the sidecar **beats
  in-process Python and is the most stable** (B3 Mixtral, ~13B active).
- **Track A (mock, zero compute):** there is no engine work to hide behind, so
  the per-token hop is on the naked critical path. At high concurrency on
  long-output shapes the hop **saturates** → the sidecar is the **least stable**
  of the four. This is the same regime as the extreme-low-compute MoE corner
  in Track B1 (Qwen3-30B-A3B, ~3B active), pushed to its limit (compute → 0).

So Track A is the *overhead-bound endpoint* of the B0→B3 arc: the mock is
"0B active params," where the sidecar's hop cost is maximal and unhidden.

## Stability summary

- **c1 sidecar:** clean at low/moderate load; degrades at C≥2048 on heavy
  shapes — worst `dp4_8192x1024_c4096` = **29.39%**, also 8.17%
  (`dp1_8192x1024_c2048`), 7.15% (`dp4_32x512_c4096`), 4.95%
  (`dp4_4096x256_c4096`). The gRPC hop saturates.
- **c4 native:** every high-concurrency point < 1.3%; the only > 5% rows are
  cold-start warmup at C∈{1,16} (first requests race engine-ready), consistent
  with the 2026-06-09 hand-run. No load-driven failures.
- **c2/c3 Python:** 0% everywhere (lone 100% = frontend-crash artifact).

## Frontend-death incident + fix

During the original automated sweep, the shared `python -m dynamo.frontend`
process accumulated resources over a multi-hour, 168-point run and **crashed at
the single most demanding point** — `c3_dp4_8192x1024_c4096` (4096 concurrent ×
8192-token prompts), with a 2.4 GB frontend log. All 56 subsequent **config-4**
points then ran ~7 h later against the dead frontend → instant 503 →
100% fail + WAIT_READY TIMEOUT in the original `agg.csv`.

- **Diagnosis:** *not* a config-4 bug. Disk was fine (679 G free); the frontend
  itself had died at the c4096/heavy-shape burst, and config-4 (which ran last)
  inherited a dead frontend. Config-4 backend registration was byte-for-byte
  identical to the healthy 2026-06-09 hand-run.
- **Fix:** restarted the frontend fresh and re-ran **config 4 in isolation**
  (anchor-skip disabled, full 64-point matrix). **All points completed clean**
  (< 1% at every high-concurrency point; the only > 5% are c1/c16 warmup),
  and the fresh frontend survived `c4_dp4_8192x1024_c4096` (0.36% fail) — the
  same extreme point that crashed it during the long original run. This
  confirms the death was **cumulative frontend resource growth** over a very
  long sweep, triggered by the c4096/8192x1024 burst — not a per-config bug.
  Whether config 3 alone would pass on a fresh frontend is untested (only
  config 4 was re-run, per scope).

## Caveats

- GPU-free mock only: this measures the **frontend + transport ceiling**
  (scheduling, engine-core messaging, detok/streaming, HTTP/SSE), *not* model
  quality or real-engine throughput. For the real-engine picture see Track B.
- `wall = max(shard duration)` slightly overestimates aggregate throughput but
  is applied uniformly, so the comparison is fair.
- Original 32x512/DP1 leg used anchor-skip (C∈{256,512,1024,2048} skipped for
  some configs); the config-4 re-run disabled it, so c4's 32x512 column is the
  most complete.

## Data provenance

- Configs 1/2/3 (+ original broken config-4 rows): `scripts/trackA/results/agg.csv`
  (242 rows). The 56 `c4_*` rows there are the frontend-death artifacts.
- Config-4 re-run (clean, supersedes the above): `scripts/trackA/results/agg_c4_rerun.csv`.
- Harness (on host `computelab-build-4`, not in repo): `/tmp/connorc/trackA_runall.sh`,
  `trackA_driver.sh`; re-run driver `trackA_driver_c4.sh` + `c4_rerun.sh`;
  raw shard JSONs under `/tmp/connorc/bench/trackA*/`.
