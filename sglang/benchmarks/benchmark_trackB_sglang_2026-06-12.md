# Track B (SGLang) — Sidecar vs In-Process, Real Engine

**Dates:** 2026-06-12 (initial, faulty board) → 2026-06-14 (full sweep on a
stable board). SGLang counterpart to the vLLM `benchmark_trackB_4way_2026-06-10.md`
/ `benchmark_trackB_rerun_eager_connpool_2026-06-11.md`.

## How this differs from the vLLM Track B

The vLLM Track B is a **4-way** sweep (c1 sidecar, c2 legacy-Python, c3
unified-Python, c4 native-Rust). For SGLang it is **2-way by construction**:

- **No c4** — there is no SGLang native-Rust in-process backend (vLLM-only,
  `dynamo-vllm-rs-backend`). SGLang's sidecar bridges the Python scheduler over
  OpenEngine; there is no in-process Rust engine-core client to compare against.
- **No GPU-free mock** — SGLang has no `vllm-mock-engine` equivalent.

So the comparison is the OpenEngine **sidecar** (c1) vs the existing **in-process
Python** worker (`python -m dynamo.sglang`, c2). Both drive the same Python SGLang
scheduler on the same GPU; the only variable is the **OpenEngine gRPC process
boundary** — isolating the hop cost, the same question the vLLM Track B rerun
answered.

## Configs

| # | Config | Path |
|---|---|---|
| c1 | **SGLang sidecar (ours)** | `dynamo-sglang-sidecar` → OpenEngine gRPC :50051 → `sglang.launch_server --openengine-port` (fork + `_core`) → scheduler |
| c2 | In-process Python | `python -m dynamo.sglang` (in-process `sgl.Engine`) |

## Hardware & environment

- **GPU:** computelab H100-80GB-HBM3, 1 GPU, TP1. **Board matters** (see fault
  finding): initial runs used the `mg62g4100` board (`ipp2-070x`), which faults
  under load; the clean full sweep used the **`h12dsgocpu`** board (`s4124-0129`),
  partition `h100-80gb-hbm3@ts6/h12dsgocpu/1gpu-48cpu-256gb`.
- **Image:** GitLab `...dynamo:4670f248c...-sglang-amd64` (sglang 0.5.12.post1,
  torch 2.11+cu130, sgl-kernel 0.4.2.post2).
- **Engine builds:** c2a = image sglang; c2b/c1 = the **fork** build (overlaid /
  via `PYTHONPATH`, `SGLANG_SKIP_SGL_KERNEL_VERSION_CHECK=1`). Both eager
  (`--disable-cuda-graph --disable-piecewise-cuda-graph`).
- **Common:** `--mem-fraction-static 0.85`, `--max-running-requests 256`.
- **Client:** `python -m sglang.bench_serving --backend vllm` → Dynamo frontend
  (:8000), `--dataset-name random`, in=32 out=512, `num-prompts = 8×conc`
  (conc 256 uses 4×).

## Model & workload

`Qwen/Qwen3-8B` (TP1), shape 32×512 — the **B0b "parity"** point of the vLLM arc.

## Results — full matched sweep on the stable board

Both configs: **fork** sglang build, eager, `h12dsgocpu` H100 board, identical
client. The complete same-board comparison (out-tok/s):

| conc | c1 sidecar | c2 in-process | sidecar Δ | c1 TTFT / TPOT (ms) | c2 TTFT / TPOT (ms) |
|---|---:|---:|---:|---|---|
| 16  | 766.0   | 750.3   | +2.1% | 89 / 20.8  | 99 / 21.2  |
| 64  | 2983.1  | 2964.0  | +0.6% | 102 / 21.3 | 156 / 21.3 |
| 256 | 10434.1 | 10191.6 | +2.4% | 211 / 24.1 | 510 / 24.1 |

All runs 100% completed (c1: 128/512/2048 prompts; c2: 128/512/1024). The c2a
*image* build at conc 16 also landed in band (749–767) before its board faulted.

**Headline: the OpenEngine sidecar reaches full throughput + TPOT parity with the
in-process Dynamo SGLang worker across the entire sweep (conc 16→256).** The gRPC
process hop costs ≈0 — c1 is within ~+2% of c2 at every point (slightly *higher*,
i.e. noise-level). This matches the vLLM Track B rerun conclusion and the Track B0
8B finding. Notably the sidecar's **TTFT is consistently lower** than in-process
(89 vs 99, 102 vs 156, 211 vs 510 ms) — the standalone `launch_server` engine +
the sidecar's connection pool front-load requests more smoothly than the
in-process scheduler at high concurrency.

## Fault finding — the conc 64+ "wall" was a bad GPU board, not the sidecar

Two distinct issues were diagnosed and resolved:

1. **Load-time (fixed by a flag):** `dynamo.sglang` enables **piecewise CUDA
   graphs** by default; their `warmup_compile` (`torch.compile`) hit `CUDA error:
   unknown error` and wedged the GPU. `--disable-cuda-graph` does NOT cover it —
   the separate **`--disable-piecewise-cuda-graph`** flag (what `agg.sh` uses) is
   required. With it, the worker loads clean.

2. **Runtime conc-64 fault = bad board (fixed by moving partitions).** After the
   load fix, a `next_token_ids.to("cpu")` D2H copy threw `cudaErrorUnknown` at
   conc 64 and the GPU fell off the bus (`6B:00.0 Unknown Error`). This was
   **reproducible and build-independent** — image build (ipp2-0713/0714) *and*
   fork build (ipp2-0701) both died at the same ~128-request trigger, 5 GPU
   wedges total. It was **NOT** OOM and NOT the sidecar. **Root cause: the
   `mg62g4100` board.** Moving to the `h12dsgocpu` board (same H100-80GB-HBM3
   GPU) made the *entire* sweep — conc 16/64/256 — run clean. So:
   - The earlier "conc 64+ unobtainable" conclusion was wrong; it was a bad board.
   - c1's earlier conc-256 "collapse" was this same `mg62g4100` GPU fault, **not**
     a sidecar high-concurrency cliff.

## Status — what's measured vs pending

- **Complete.** Both c1 (sidecar) and c2 (in-process) full sweeps (conc 16/64/256)
  captured on the same stable `h12dsgocpu` board with the same fork build → the
  matched table above. Both fault root-causes resolved.
- The c1 run required rebuilding the sidecar stack on the node:
  `cargo build -p dynamo-sglang-sidecar` (debug) + the fork `_core`
  (`cargo build` in `sglang/rust/sglang-grpc` → `lib_core.so` placed as
  `sglang/srt/grpc/_core.cpython-312-*.so`; the image's stock `_core` lacks
  `start_openengine_server`), via the `/tmp` toolchain bootstrap (rustup +
  protoc 27.3 with `PROTOC_INCLUDE` + libclang for nixl-sys bindgen,
  `BINDGEN_EXTRA_CLANG_ARGS=-I/usr/lib/gcc/x86_64-linux-gnu/13/include`,
  `SGLANG_SKIP_SGL_KERNEL_VERSION_CHECK=1`). Launched via
  `sglang.launch_server --openengine-port 50051` (fork) +
  `dynamo-sglang-sidecar --openengine-endpoint 127.0.0.1:50051` + frontend.

## Caveats

- **2-way only**, **1 GPU**, **one model/shape** (Qwen3-8B, 32×512) — a slice of
  the vLLM Track B arc (B0–B3). B2/B3 (TP2) + the 8192×1024 shape need ≥2 GPUs.
- **Board sensitivity:** the `mg62g4100` H100 board faults under sustained load
  with `cudaErrorUnknown`; use `h12dsgocpu` (or another board) for load testing.
- Sidecar functionally validated end-to-end separately (agg / KV-routing / P/D /
  image MM — see `project_sglang_sidecar_phaseA`); this doc is the perf leg.

## Data provenance

- c1 (sidecar) full sweep + c2b (fork, in-process) full sweep: 2026-06-14 on
  `s4124-0129` (h12dsgocpu board). Drivers: `scripts/trackB/bench_c2_fork_sglang.sh`
  (c2); node scripts `/tmp/connorc/{build,bootstrap,run_c1}.sh` (c1, built by the
  review-test-deploy agent). c1 result JSONs `/tmp/connorc/c1_c{16,64,256}.json`.
- c2a (image, in-process) conc 16: 2026-06-12 on `ipp2-0713`/`0714` (mg62g4100;
  conc 64 board-faulted). Driver: `scripts/trackB/bench_c2_sglang.sh`.
- Earlier c1 16/64 on `ipp2-0701` (mg62g4100) agreed with the stable-board numbers.
- Per-point JSON node-local, lost on dealloc.
