# Track B Rerun — Symmetric-Eager c1-vs-c4 + Connection Pool (B1, B2)

**Date:** 2026-06-11
**Run type:** GPU rerun of the two decisive Track B legs (B1 low-active MoE,
B2 compute-bound dense) with the **two confounds removed** from the original
four-way sweep (`benchmark_trackB_4way_2026-06-10.md`). This run answers,
cleanly: **once the sidecar (c1) and the in-process native Rust backend (c4)
are on equal footing, does the sidecar's extra OpenEngine gRPC hop cost
anything?**

## The two confounds this rerun removes

The 4-way sweep reported a B1 "regression" — at `Qwen3-30B-A3B` (~3B active) the
sidecar trailed the field on throughput and **collapsed 29.7% fail** at
`8192×1024 / c64`. Two confounds were baked into that comparison:

1. **CUDA-graph asymmetry.** Configs 1/2/3 ran `--enforce-eager`; **config 4 did
   not** (CUDA graphs on). So c4's throughput/TTFT lead mixed the native backend
   *with* its CUDA-graph advantage. The 4-way doc flagged this as "the key
   confound" and said the clean read was c1 vs c2/c3 (eager Python) — but never
   put c1 and c4 on the same footing.
2. **Single gRPC connection.** The sidecar used **one** shared HTTP/2 channel to
   `vllm-rs`. The Track-A conn-pool A/B
   (`benchmark_trackA_connpool_ab_2026-06-11.md`) localized the 29% failure
   cliff to that single h2 codec task saturating, and showed an 8-connection
   pool removes it on the GPU-free mock — predicting the pool would be "decisive
   only in the [real-engine] overhead-bound regime." B1 is that regime.

This rerun fixes both: **config 4 forced eager (`C4_ENFORCE_EAGER=1`)** and
**config 1 with `OPENENGINE_CONNECTIONS=8`**. Only c1 and c4 are run (both use
the `vllm-rs` Rust frontend, so they differ by **exactly one thing: the
OpenEngine gRPC process boundary**). This is the cleanest possible isolation of
the sidecar's hop cost.

## Hardware & environment

- **Host:** dlcluster node `4u4g-0072` (2× H100 NVL, 94 GB each), cuda13 dynamo
  image (`...ai-dynamo/dynamo:30bdd4b362...-vllm-dev-cuda13`), run in detached
  docker (`--gpus all --ipc=host`, `/work` = host `/tmp/connorc`).
- **Binaries (release):** `dynamo-vllm-sidecar` (c1, with the connection pool),
  `dynamo-vllm-rs-backend` (c4); both drive a managed Python EngineCore via
  `vllm-rs`. vLLM fork forced via `PYTHONPATH=/work/src/vllm` (the fork wheel's
  14 compiled `.so` overlaid into the source tree to satisfy `vllm._C`).
- **Driver:** `scripts/trackB/trackB_driver.sh` via `trackB_rerun.sh`
  (`infra_up`; `run 1`; `run 4`; `aggregate`; `infra_down`).
- **Both configs eager** this run. `OPENENGINE_CONNECTIONS=8` on c1.
- Shapes `32×512` (full conc 1–256) + `8192×1024` (conc capped ≤64);
  `vllm bench serve --dataset-name random --ignore-eos`, 360 s point timeout.

## B1 — Qwen3-30B-A3B, ~3B active (TP1), eager c1(pool=8) vs eager c4

### 32×512 (out-tok/s; TTFT ms; TPOT ms; all points 0% fail both configs)

| conc | c1 out-tok/s | c4 out-tok/s | c1/c4 | c1 TTFT | c4 TTFT | c1 TPOT | c4 TPOT |
|---|---|---|---|---|---|---|---|
| 1 | 25 | 25 | — | 93 | 83 | 39.8 | 40.1 |
| 8 | 200 | 201 | 1.00 | 126 | 126 | 39.8 | 39.7 |
| 16 | 401 | 399 | 1.00 | 133 | 129 | 39.7 | 39.9 |
| 32 | 788 | 801 | 0.98 | 141 | 139 | 40.4 | 39.8 |
| 64 | 1580 | 1573 | 1.00 | 156 | 164 | 40.3 | 40.4 |
| 128 | 3055 | 3044 | 1.00 | 228 | 254 | 41.5 | 41.6 |
| 256 | 5770 | 5825 | 0.99 | 395 | 404 | 43.6 | 43.2 |

### 8192×1024 (conc ≤64; all points 0% fail both configs)

| conc | c1 out-tok/s | c4 out-tok/s | c1/c4 | c1 TTFT | c4 TTFT | c1 TPOT | c4 TPOT |
|---|---|---|---|---|---|---|---|
| 1 | 25 | 25 | 1.00 | 406 | 442 | 39.6 | 39.3 |
| 8 | 193 | 191 | 1.01 | 987 | 1065 | 40.5 | 40.8 |
| 16 | 371 | 376 | 0.99 | 1964 | 2180 | 41.1 | 40.3 |
| 32 | 581 | 576 | 1.01 | 3767 | 4047 | 43.1 | 43.3 |
| **64** | **606** | 592 | **1.02** | 42605 | 44104 | 51.2 | 52.3 |

**B1 verdict:** with both configs eager and c1 pooled, **c1 ≈ c4 at every
point** (throughput within ±2%, TPOT identical, c1 marginally lower TTFT at most
points). The `8192×1024 / c64` point that **failed 29.7%** in the 4-way doc now
runs **0% fail, 128/128 completed** on both — and c1's heavy-shape peak moves
from c32 (the old collapse boundary) up to **c64 = 606 out-tok/s**, edging c4.
The B1 "regression" was entirely the two confounds; remove them and it vanishes.

## B2 — Qwen3-32B dense, 32B active (TP2), eager c1(pool=8) vs eager c4

### 32×512 (all points 0% fail both configs)

| conc | c1 out-tok/s | c4 out-tok/s | c1/c4 | c1 TTFT | c4 TTFT | c1 p99 TTFT | c4 p99 TTFT | c1 TPOT | c4 TPOT |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 24.2 | 24.1 | 1.00 | 50 | 45 | 81 | 51 | 41.4 | 41.5 |
| 8 | 188.8 | 188.2 | 1.00 | 134 | 138 | 177 | 175 | 42.2 | 42.3 |
| 16 | 384.1 | 377.8 | 1.02 | 815 | 151 | 14789 | 177 | 40.1 | 42.1 |
| 32 | 748.4 | 744.7 | 1.01 | 549 | 207 | 8344 | 264 | 41.8 | 42.6 |
| 64 | 1513.7 | 1476.1 | 1.03 | 605 | 310 | 15750 | 419 | 41.1 | 42.8 |
| 128 | 2942.5 | 2928.9 | 1.00 | 1248 | 528 | 22287 | 724 | 41.0 | 42.7 |
| 256 | 4708.9 | 4687.9 | 1.00 | 1687 | 857 | 27743 | 957 | 51.0 | 53.0 |

### 8192×1024 (conc ≤64; all points 0% fail both configs)

| conc | c1 out-tok/s | c4 out-tok/s | c1/c4 | c1 TTFT | c4 TTFT | c1 TPOT | c4 TPOT |
|---|---|---|---|---|---|---|---|
| 1 | 23.5 | 23.4 | 1.00 | 1361 | 1331 | 41.3 | 41.5 |
| 8 | 167.4 | 171.7 | 0.97 | 6249 | 3081 | 41.6 | 43.6 |
| 16 | 303.4 | 307.6 | 0.99 | 7086 | 5745 | 45.7 | 46.3 |
| 32 | 511.2 | 508.7 | 1.01 | 12616 | 11414 | 50.0 | 51.5 |
| 64 | 413.9 | 434.4 | 0.95 | 47886 | 42380 | 94.0 | 92.4 |

**B2 verdict:** at the fully compute-bound dense regime, **c1 matches c4 on
throughput (±2–5%, often slightly ahead) and TPOT (identical), 0% fail
everywhere.** The native backend's small ~4–5% throughput edge in the 4-way doc
was its CUDA graphs; removing them yields parity. **The one residual sidecar
cost is TTFT, not throughput:** on the small shape at high concurrency the
sidecar's mean TTFT runs higher than c4 (c256: 1687 vs 857 ms) with a much fatter
tail (c128 p99: 22.3 s vs 0.72 s), while delivering equal-or-better aggregate
throughput and 0% fail. A follow-up pool sweep (c1 `32×512` re-run at
`OPENENGINE_CONNECTIONS` ∈ {1, 8, 16}) shows this tail is **pool-independent** —
p99 TTFT is within run-to-run noise across all three pool sizes at every conc,
with the same onset at c16 (~15 s p99 regardless of connection count; see
*Caveats*). So it is **not** per-connection HTTP/2 head-of-line blocking and not
a connection-multiplexing artifact; it is a pool-independent serialization in
the c1 request path (sidecar → `vllm-rs` OpenEngine server → EngineCore) that
c4's direct ZMQ path avoids. It shifts the TTFT distribution, but does **not**
reduce throughput or cause drops.

## Headline findings

1. **Eager-vs-eager: the sidecar matches native Rust on throughput, TPOT, and
   stability — at both ends of the compute arc.** The 4-way doc's "native Rust is
   fastest" ordering was the CUDA-graph confound. With c4 eager, c1 and c4 are at
   throughput parity at B1 (±2%) and B2 (±2–5%, c1 often ahead), TPOT identical,
   0% fail. **The sidecar's extra OpenEngine gRPC process boundary costs
   essentially nothing in throughput/TPOT/stability.**

2. **The connection pool removes the B1 collapse on a real engine.** B1
   `8192×1024 / c64` went **29.7% fail → 0% fail** (128/128) with
   `OPENENGINE_CONNECTIONS=8`. This confirms the Track-A prediction exactly: the
   single-h2-codec saturation was the cause, and pooling is the fix in the one
   real-engine overhead-bound regime where the limiter actually bit.

3. **The residual cost is a TTFT premium, concentrated at high-conc small
   shapes — and it is pool-independent.** ~5 ms fixed at conc=1 (B2: 50 vs 45 ms),
   growing to a fat TTFT tail under burst on the small shape (B2 c256: 1687 vs
   857 ms mean; c128 p99 22.3 s vs 0.72 s). A pool sweep (c1 at
   `OPENENGINE_CONNECTIONS` ∈ {1, 8, 16}) leaves the tail unchanged — identical
   p99 TTFT at every conc, same onset at c16 — so it is **not** gRPC connection
   multiplexing / HTTP/2 HOL. It is a pool-independent serialization somewhere in
   the c1 path that c4's direct ZMQ path avoids. It does not reduce throughput or
   cause failures — it is a latency-distribution cost of the extra hop, paid
   where there is no compute to amortize it behind. Consistent with the H100 agg
   A/B's "~8 ms fixed TTFT hop at conc1, amortized under load." (Note this is a
   *distinct* phenomenon from the heavy-shape failure cliff in finding #2: the
   pool fixes the cliff but does nothing to this small-shape tail.)

## How this revises the 4-way doc

The 4-way doc's B1 leg should be read as **two stacked confounds, not a sidecar
property.** Its B1 numbers (c1 4351 vs c4 6483 out-tok/s @ 32×512/c256; c1
29.7% fail @ c64) decompose as: c4's CUDA-graph edge (~10–12% at this
overhead-bound model) + c1's single-connection throttling/collapse (the rest).
Put c4 on eager and give c1 the pool, and B1 is **parity, 0% fail** — same as
B2. The arc's *shape* (sidecar standing rises with per-token compute vs **eager
Python** c2/c3) still holds and is unchanged by this rerun; what changes is the
**c1-vs-c4 read**: against the *same Rust frontend stack*, the hop is free on
throughput/TPOT/stability at every compute regime, with only a TTFT-tail premium
remaining.

## Caveats / data notes

- **B2 `c1_8192×1024 / c1` — originally dropped on the 360 s budget edge, since
  rerun and at parity.** At conc=1 the heavy shape runs 8 strictly-sequential
  8K-prompt/1K-output requests, landing right at the 360 s point budget; on the
  main run the sidecar's small per-request TTFT premium tipped the total just
  past it (the requests weren't failing — the point just didn't finish all 8 in
  the cap), while `c4` squeaked in (wall ≈ 350 s). Re-run config-1-only with a
  **900 s timeout** (`scripts/trackB/trackB_onepoint.sh`, into the same rundir):
  it completes **8/8, 0% fail, wall 359.4 s, 23.5 out-tok/s, TTFT 1361 ms** —
  dead-even with `c4` (23.4 out-tok/s, 1331 ms; ~2% TTFT premium, TPOT
  identical). So this point is parity too; the "timeout" was purely the
  wall-clock cap, not a sidecar deficit. The table above reflects the rerun.
- **The small-shape TTFT tail is pool-independent (conn-sweep).** To test
  whether the B2 `32×512` high-conc tail was per-connection HTTP/2 HOL blocking
  (the tail's onset at c16 coincides with "2 streams/connection" at pool=8), c1
  `32×512` was re-run at `OPENENGINE_CONNECTIONS` ∈ {1, 16} and compared to the
  main run's pool=8. **p99 TTFT (ms) is within run-to-run noise across all three
  pool sizes at every conc** — the tail turns on at c16 regardless of connection
  count, refuting the HOL hypothesis:

  | conc | pool=1 | pool=8 | pool=16 |
  |---|---|---|---|
  | 1 | 85 | 81 | 81 |
  | 8 | 176 | 177 | 176 |
  | 16 | 14983 | 14789 | 15332 |
  | 32 | 8318 | 8344 | 8157 |
  | 64 | 16366 | 15750 | 16412 |
  | 128 | 22768 | 22287 | 22886 |
  | 256 | 27706 | 27743 | 27719 |

  So the connection pool's benefit is **only** the heavy-shape failure-collapse
  fix (finding #2); it does nothing for this small-shape latency tail, which
  comes from a pool-independent serialization in the c1 path. Sweep rundirs:
  `run-32b-pool{1,16}/aggregate.json` (pool=8 = `run-32b-rerun`).
- **Heavy-shape TTFT is large and noisy by construction** (8192-token prompts,
  `wall = max(shard)`); the robust signals are the throughput/TPOT parity and
  the 0% fail across the sweep, not the absolute heavy-shape TTFT values.
- **Only c1 and c4 were run** (the clean Rust-frontend pair). Eager-Python
  (c2/c3) comparison is unchanged from the 4-way doc.

## Data provenance

- `aggregate.json` + raw per-point `c{1,4}/*.json` + `*.client.log` on dlcluster
  `4u4g-0072` under `/tmp/connorc/bench/trackB/results/run-{30b,32b}-rerun/`.
- Driver: `scripts/trackB/trackB_driver.sh`; rerun wrapper
  `scripts/trackB/trackB_rerun.sh` (`TP`, `C4_ENFORCE_EAGER=1`,
  `OPENENGINE_CONNECTIONS=8`).
- Companion docs: `benchmark_trackB_4way_2026-06-10.md` (the original sweep this
  reruns), `benchmark_trackA_connpool_ab_2026-06-11.md` (the pool root-cause/fix
  this confirms on a real engine).
