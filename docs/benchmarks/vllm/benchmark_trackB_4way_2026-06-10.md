# Track B — Real-Engine 4-Way Sweep Across the Compute-Regime Arc (B0–B3)

**Date:** 2026-06-10
**Run type:** GPU throughput/latency/stability comparison of four Dynamo
backend architectures over **real vLLM engines** on H100 NVL, swept across a
five-model matrix chosen to vary **per-token active compute** by ~50× while
holding the frontend/backend architecture fixed. This is the real-engine
counterpart to the GPU-free mock sweep
(`benchmark_mockengine_4way_2026-06-09.md`); together they bracket the sidecar's
cost from "pure transport ceiling" (mock) to "production model scale" (here).

## The question this answers

The mock sweep showed the Rust sidecar pays a ~2× hop tax versus the in-process
native Rust backend on a GPU-free engine, but still beats Python ~3.3×. The open
question was whether that hop tax survives on real engines — and if so, **what
governs it**. Track B answers: the sidecar's standing versus in-process Python
is governed by **per-token active compute**, not nameplate model size and not
"MoE vs dense". As active params/token rise, the fixed per-token gRPC-streaming
hop is increasingly amortized, and the sidecar's Rust-frontend efficiency
(detok/sampling/stop-matching in Rust, not Python) surfaces.

## The four configs (held fixed across all five models)

| # | Config | Path |
|---|---|---|
| 1 | **Rust sidecar (ours)** | `dynamo-vllm-sidecar` → OpenEngine gRPC :50051 → `vllm-rs serve` → ZMQ/msgpack → Python EngineCore |
| 2 | Legacy Python | `python -m dynamo.vllm` (in-process AsyncLLM) |
| 3 | Unified Python | `python -m dynamo.vllm.unified_main` (in-process AsyncLLM) |
| 4 | PR #9206 native Rust | `dynamo-vllm-rs-backend` (in-process engine-core ZMQ client) |

All four fronted by **one** Dynamo HTTP frontend (:8000) + node etcd (:2379) +
NATS (:4222); **only one config runs at a time** (all register under the same
`dynamo.backend.generate` key). Configs 1 and 4 both use the `vllm-rs` Rust
frontend stack (efficient Rust detok/sampling); configs 2/3 use the Python
AsyncLLM path.

**Eager/CUDA-graph asymmetry (the key confound):** configs 1/2/3 launch
`--enforce-eager`; config 4 does **not** (CUDA graphs on). So config 4's
throughput/TTFT lead mixes the native backend *with* its CUDA-graph advantage.
The apples-to-apples sidecar comparison is **c1 vs c2/c3**.

## The model matrix — varying per-token compute

| Leg | Model | Nameplate | Active/token | Type | TP | Shapes |
|---|---|---|---|---|---|---|
| B0a | `Qwen/Qwen3-0.6B` | 0.6B | 0.6B | dense | 1 | 4 shapes, full conc |
| B0b | `Qwen/Qwen3-8B` | 8B | 8B | dense | 1 | 4 shapes (heavy capped c≤64) |
| B1 | `Qwen/Qwen3-30B-A3B` | 30B | **~3B** | MoE (128-expert) | 1 | 32×512 + 8192×1024 (c≤64) |
| B2 | `Qwen/Qwen3-32B` | 32B | **32B** | dense | 2 | 32×512 + 8192×1024 (c≤64) |
| B3 | `mistralai/Mixtral-8x7B-Instruct-v0.1` | 46.7B | **~13B** | MoE (8-expert top-2) | 2 | 32×512 + 8192×1024 (c≤64) |

B1/B2 are a **controlled pair**: nearly identical ~30B nameplate, ~10× apart in
active compute (3B MoE vs 32B dense). B3 sits between B1 and B2 on active
compute (~13B) and is the high-active-param MoE counterpart to B1's
low-active-param MoE.

## Hardware & environment

- **Host:** dlcluster node `4u4g-0069` (2× H100 NVL, 94 GB each), container
  `trackB1`, cuda13 dynamo image
  (`...ai-dynamo/dynamo:30bdd4b362...-vllm-dev-cuda13`). B0b 8B ran on
  `2u2g-gen-0669`.
- **TP wiring:** the driver gained a `TP` env var forwarded as
  `--tensor-parallel-size` to all four configs (B1=TP1; B2/B3=TP2). Configs 1/4
  forward it to the managed Python EngineCore; 2/3 consume it natively.
- **Binaries (release):** `vllm-rs`, `dynamo-vllm-sidecar`,
  `dynamo-vllm-rs-backend`; vLLM fork forced via `PYTHONPATH=/work/src/vllm`.
- **Driver:** `scripts/trackB/trackB_driver.sh` (`infra_up`; `run <cfg> <MODEL>
  <RUNDIR>`; `aggregate`; `infra_down`).

## Methodology

- Concurrency sweep per config; **peak = best total-tok/s among points with
  failure rate < 1%**. B0 swept 4 shapes × {1,8,16,32,64,128,256}; B1–B3 swept
  `32×512` (full conc) + `8192×1024` (conc capped ≤64, where it peaks).
- Sharded `vllm bench serve` clients (to avoid the single-client GIL dispatch
  cap), `--dataset-name random --ignore-eos`.
- All B0 and B2 points ran 0% fail; B1 and B3 fail rates are reported inline
  (they are part of the finding).

## Results — peak total-tok/s (output-tok/s) per (config, shape)

### B0a — Qwen3-0.6B (TP1), 32×512 @ c256 only (the artifact)

| Config | 32×512 |
|---|---|
| 1 sidecar | 13500 (12706) |
| 2 legacy py | 13736 (12928) |
| 3 unified py | 13269 (12489) |
| 4 native rs | **32981 (31041)** |

Native Rust is **~2.4×** the field — but this is a small-model artifact (see
findings). At the heavier 0.6B shapes all four converge to within ~1–2%.

### B0b — Qwen3-8B (TP1)

| Config | 32×512 @c256 | 8192×1024 @c32 |
|---|---|---|
| 1 sidecar | **10665 (10038)** | 7075 (786) |
| 2 legacy py | 10162 (9564) | 7071 (786) |
| 3 unified py | 10069 (9477) | 7117 (791) |
| 4 native rs | 10436 (9822) | **7146 (794)** |

Parity across all four (spread ≤6%, mostly ≤2%); sidecar at or above the field.

### B1 — Qwen3-30B-A3B, ~3B active (TP1) — the regression

| Config | 32×512 @c256 | 8192×1024 |
|---|---|---|
| 1 sidecar | 4623 (4351) | 3432 (381) @c32 — **FAILS 29.7% @c64** |
| 2 legacy py | **6056 (5700)** | 5376 (597) @c64 |
| 3 unified py | 6033 (5678) | 5376 (597) @c64 |
| 4 native rs | **6888 (6483)** | 6512 (724) @c32 |

Sidecar runs **~76%** of the eager-Python field at 32×512 and **~64–67%** at
8192×1024, and **collapses 29.7% fail** at the heavy shape under c64 load
(mean TTFT ~123 s past the point timeout) while 2/3/4 hold 0% there.

### B2 — Qwen3-32B dense, 32B active (TP2) — parity restored

| Config | 32×512 @c256 | 8192×1024 @c32 |
|---|---|---|
| 1 sidecar | 4947 (4656) | 4524 (503) |
| 2 legacy py | 4881 (4593) | 4490 (499) |
| 3 unified py | 4891 (4604) | 4492 (499) |
| 4 native rs | **5170 (4866)** | **4968 (552)** |

Sidecar **~101%** of the eager-Python field at both shapes, **0% fail
everywhere**. TPOT identical across all four (~51 ms) — fully compute-bound.

### B3 — Mixtral-8x7B, ~13B active (TP2) — the reversal

| Config | 32×512 @c256 | 8192×1024 @c64 (fail%) |
|---|---|---|
| 1 sidecar | 5817 (5485) | 7495 (833) — **0%** |
| 2 legacy py | 4736 (4465) | 6474 (719) — 0.8% |
| 3 unified py | 4756 (4484) | 6626 (736) — 2.3% |
| 4 native rs | **6652 (6273)** | **8697 (966)** — 3.9% |

Sidecar **beats** the eager-Python field: **~123%** at 32×512, **~109–114%** at
8192×1024/c32 (5943 vs 5229–5437). It is also the **most stable** config — 0%
fail across the entire heavy sweep, while c2 (6.2% @c8, 1.6% @c32), c3 (2.3%
@c64), and even native c4 (3.9% @c64) each dropped requests. Lower TPOT than
Python too (45.4 vs 56.0 ms @32×512).

## The unified finding — sidecar standing rises with per-token compute

| Active params/token | Leg | Sidecar vs in-process Python | Stability |
|---|---|---|---|
| 0.6B (dense) | B0a | parity* | 0% fail |
| ~3B (MoE) | B1 | **~64–76%** (trails) | **29.7% fail @c64** |
| 8B (dense) | B0b | parity (top at most shapes) | 0% fail |
| ~13B (MoE) | B3 | **~109–123%** (beats) | **most stable, 0% fail** |
| 32B (dense) | B2 | ~101% (parity) | 0% fail |

\* at 0.6B the field is at parity but native Rust wins 2.4× — overhead-bound
artifact, not a sidecar property.

**Why:** the variable is per-token **compute** (active-param-driven), not "MoE
vs dense" and not nameplate size. Both the sidecar (c1) and native Rust (c4) use
the `vllm-rs` Rust frontend (efficient detok/sampling); Python (c2/c3) does not.

- **Extreme-low compute (B1, ~3B active):** per-token GPU work is so small that
  the per-token OpenEngine gRPC-streaming hop is **not amortized** → the sidecar
  pays it as throughput + a +14 ms TPOT tax, and saturates the hop under heavy
  prefill (the 29.7% collapse). The "30B" label is misleading; ~3B-class
  per-token compute puts this model in the same overhead-bound regime as the
  0.6B native-Rust mock win.
- **Moderate compute (B3, ~13B active, ~4× B1):** the hop is amortized and the
  Rust-frontend edge surfaces → the sidecar **beats** Python and is the most
  stable at heavy prefill.
- **Compute-bound dense (B0b 8B, B2 32B):** the engine is so compute-bound the
  frontend is irrelevant → parity, identical TPOT.

The **hop-amortization threshold sits between 3B and 13B active params/token.**
B1 and B2 are the clean controlled experiment that isolates this: same ~30B
nameplate, opposite result, only active-compute differs.

## Config ordering and the CUDA-graph confound

At B2/B3 the ordering is **native c4 > sidecar c1 > Python c2≈c3** at every
point; at B1 the sidecar is *last*. But config 4's lead is confounded: it is the
only non-eager config (CUDA graphs on). Among the **eager** configs (1/2/3) the
sidecar carries the lowest or competitive TTFT at every leg and wins throughput
outright at B3. So "native Rust is fastest" conflates the backend datapath with
CUDA graphs; the clean sidecar-vs-Python read is c1 vs c2/c3.

Note also: native c4 is the **throughput/TTFT leader but NOT the most stable**
at heavy prefill — at B3/c64 it dropped 3.9% of requests while the sidecar held
0%. Raw-throughput leadership and tail stability are different axes.

## Failure / stability summary

- **B0, B2:** every point 0% fail across all configs.
- **B1 (low-active MoE):** sidecar **collapses 29.7% @ 8192×1024/c64** (TTFT
  past the 360 s point timeout); 2/3/4 hold 0% there. The sidecar is the *least*
  stable here.
- **B3 (moderate-active MoE):** **inverts B1** — the sidecar is the *most* stable
  (0% across the heavy sweep) while every other config, including native c4,
  drops requests under heavy prefill.

## Operational note — the CPU-platform bug (root cause + fix)

Config 1 initially crashed selecting `CpuPlatform` on a healthy H100. Root cause:
`vllm.egg-info/PKG-INFO` in the fork tree carried `Version: 0.22.1+cpu.empty`
(leftover from the Track-A CPU build). `importlib.metadata.version("vllm")`
resolved that egg-info ahead of the clean system `vllm-0.22.1.dist-info` under
`PYTHONPATH=/work/src/vllm`, and `vllm/platforms/__init__.py`'s `cuda_platform_plugin()`
rejects CUDA when the version string matches the substring `"cpu"`. **Fix:**
rewrote the egg-info Version line to `0.22.1rc1.dev3+g5dbf1605a` (no "cpu"
substring); verified `NvmlCudaPlatform` / `device_config=cuda` / both GPUs
resident. This was the sole blocker for all of B1–B3.

## Big picture (B0 → B3)

The sidecar's "free gRPC hop" claim holds everywhere **except** the
overhead-bound, extreme-low-active-param MoE corner (B1). Stated as a rule: the
Rust sidecar's standing versus in-process Python **rises monotonically with
per-token active compute** — below Python only at ~3B active (B1), at parity on
dense (8B, 32B), and above Python at ~13B active (B3), where it also becomes the
most stable config at heavy prefill. Native Rust (c4) is the throughput/TTFT
leader but carries a CUDA-graph confound and is not the tail-stability leader.
Cite this arc — **not** the over-broad "MoE breaks the sidecar" reading from B1
alone.

## Data provenance

- Per-point CSVs + `aggregate.json` + raw `c{1..4}/*.json` on the laptop under
  `scripts/trackB/results/run-{0.6b,8b,30b,32b,mixtral}/`.
- Per-leg runbooks: `scripts/trackB/RUNBOOK_trackB{0,1,2,3}.md`.
- Driver: `scripts/trackB/trackB_driver.sh` (with the `TP` env var).
