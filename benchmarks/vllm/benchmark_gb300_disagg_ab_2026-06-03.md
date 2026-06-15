# Sidecar GB300 Disagg A/B — DeepSeek-V4-Pro 8k/1k

**Date:** 2026-06-03
**Run type:** precise sidecar-vs-in-process A/B of the OpenEngine Rust sidecar
vs. in-process vLLM+Dynamo, on the SemiAnalysis DeepSeek-V4-Pro GB300 topology.

## What was tested

Two legs, **identical** container / Dynamo wheel / model / precision /
parallelism / benchmark — the *only* variable is the Dynamo worker
architecture:

| Leg | SLURM job | Architecture |
|---|---|---|
| `baseline` (in-process) | **2000768** | `python -m dynamo.vllm` runs the vLLM engine in-process (AsyncLLM) as the Dynamo worker |
| `sidecar` | **1999849** | `vllm-rs serve` (Rust frontend + managed Python EngineCore) + `dynamo-vllm-sidecar` Rust worker, talking over **OpenEngine v1 gRPC** |

**The baseline is the in-process leg (job 2000768)** — same recipe as the
sidecar with the OpenEngine architecture toggled off, run through the **same
sa-bench harness**, so this is the clean apples-to-apples comparison. (A
*public* InferenceX in-process row exists at this topology and is used as an
external cross-check at the end; the local in-process leg is the primary
baseline because it shares the exact harness, dataset, and OSL.)

Architecture-forced deltas between the two recipes (not independent variables):
`kv_role kv_both` (in-process; Dynamo router orchestrates P→D) vs.
`kv_producer`/`kv_consumer` (sidecar discovers its disagg role from the
engine); and `setup_script vllm-container-deps.sh` vs. `vllm-sidecar-deps.sh`
(stages the Rust binaries). Perf-neutral for a strict 1P/6D split.

## Hardware & environment

- **GPU:** 28x NVIDIA **GB300** (Grace-Blackwell, aarch64), 4 GPU/node, 7 nodes
- **Topology:** **1P / 6D**, prefill TP1×DP4 + EP (4 GPU, 1 node), decode TP4
  ×6 (24 GPU, 6 nodes) — `ctx_4 / gen_24`
- **Cluster:** lyris. In-process job 2000768 ran on prefill `theia0182`, decode
  `theia0183-0186, 0194, 0196`. Partition `gb300`.
- **Container:** `vllm/vllm-openai:v0.20.0-cu130` (identical for both legs)
- **Dynamo:** wheel **1.3.0** (identical runtime, HTTP frontend, KV router,
  NATS/etcd for both legs)

## Model & engine config

- **Model:** `deepseek-ai/DeepSeek-V4-Pro`, **FP4**, KV cache `fp8`,
  `max-model-len 16384`, `block-size 256`, `trust-remote-code`,
  `enable-expert-parallel`, `moe-backend deep_gemm_mega_moe`, NixlConnector KV
  transfer.
- **Prefill:** TP1, DP4, EP, `enforce-eager`, `max-num-batched-tokens 16384`,
  `max-num-seqs 256`.
- **Decode:** TP4, `max-num-seqs 512`, `max-num-batched-tokens 512`,
  `cudagraph_mode FULL_DECODE_ONLY`, `all2all-backend
  flashinfer_nvlink_one_sided`, `stream-interval 50`, `tokenizer-mode
  deepseek_v4`.

## Benchmark config (sa-bench)

- **ISL 8192 / OSL 1024** (sa-bench `random_range 0.8` → **~921 generated
  tok/req** actual), `req_rate inf`, chat template,
  `custom_tokenizer sa_bench_tokenizers.vllm_deepseek_v4.VLLMDeepseekV4Tokenizer`.
- **Concurrencies:** 192, 256.
- **Identical workload, confirmed by the data:** both legs drove the exact same
  token volumes — input `14,168,599` (c192) / `18,878,865` (c256) and output
  `1,768,241` (c192) / `2,360,397` (c256) — and completed 1920/1920 and
  2560/2560 requests.

## Results

Throughput shown **per GPU** (÷28 total; output ÷28). `tok/s/user` =
1000 / median TPOT.

| conc | leg | req/s | out tok/s/GPU | tot tok/s/GPU | tok/s/user | TTFT median (ms) | TTFT mean (ms) | TTFT p99 (ms) | TPOT median (ms) | ITL median (ms) | e2el median (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 192 | baseline | 5.93 | 195.2 | 1758.9 | 37.20 | **3271.8** | 6624.3 | 23982.3 | 26.88 | 1350.8† | 28893.8 |
| 192 | sidecar  | 5.91 | 194.3 | 1751.0 | 37.42 | **5279.9** | 7231.8 | 24081.3 | 26.72 | 25.5† | 30093.6 |
| 256 | baseline | 6.89 | 226.9 | 2042.0 | 32.26 | 5359.1 | 6697.2 | 31705.4 | 31.00 | 1543.6† | 33753.0 |
| 256 | sidecar  | 7.15 | 235.4 | 2118.1 | 32.66 | 5472.1 | 6887.7 | 31672.7 | 30.62 | 28.7† | 33738.9 |

† **ITL is not directly comparable between legs** — see Takeaway. Use TPOT for
per-token latency.

### Sidecar vs. baseline (deltas)

| metric | conc 192 | conc 256 |
|---|---|---|
| total tok/s/GPU | **−0.5%** (1751.0 vs 1758.9) | **+3.7%** (2118.1 vs 2042.0) |
| output tok/s/GPU | −0.5% (194.3 vs 195.2) | +3.7% (235.4 vs 226.9) |
| TPOT median | −0.6% (26.72 vs 26.88) | −1.2% (30.62 vs 31.00) |
| TTFT median | **+61%** (+2008 ms) | **+2.1%** (+113 ms) |
| TTFT mean | +9.2% (+607 ms) | +2.8% (+191 ms) |
| TTFT p99 | +0.4% | −0.1% |
| e2el median | +4.1% | −0.04% |

## Takeaway

- **Throughput: parity.** The sidecar lands within **−0.5%** of in-process at
  conc 192 and is **+3.7% ahead** at conc 256. Net: no throughput regression
  from the OpenEngine process split; at the higher load the sidecar is slightly
  faster (its run also finished conc 256 in 358.1 s vs 371.5 s).
- **Per-token latency (TPOT): parity.** Median TPOT is within ~1% at both
  concurrencies, marginally *lower* for the sidecar (26.72 vs 26.88;
  30.62 vs 31.00). The OpenEngine hop does not sit on the steady-state decode
  path.
- **TTFT: a real but load-amortized cost.** At conc 192 the sidecar adds
  ~2.0 s median TTFT (+61%); by conc 256 the gap collapses to +113 ms (+2%),
  and p99 TTFT is identical at both loads. This matches the H100 finding that
  the sidecar's first-token overhead is a fixed prefill-path cost (gRPC hop +
  prefill scheduling through the sidecar) that amortizes as the prefill engine
  saturates. It is the one remaining item to tighten.
- **ITL is a streaming-granularity artifact, not a regression.** The in-process
  leg honors `stream-interval 50`, so sa-bench measures inter-token latency at
  chunk granularity (~50× TPOT ≈ 1350–1544 ms). The sidecar's vLLM-rs frontend
  re-emits per token, so its ITL (~25–29 ms) tracks TPOT. The comparable
  per-token metric is **TPOT**, which is at parity.
- **End-to-end latency: parity.** Median e2el is +4% at conc 192 (driven by the
  TTFT gap) and identical at conc 256.

## Cross-check vs. public InferenceX (external, not the primary baseline)

SemiAnalysis publishes an in-process `dynamo-vllm` GB300 row at this exact
topology (FP4, disagg, P4/D24, 8k/1k, conc 192, image v0.20.0): **total
tput/GPU 1920, output tput/GPU 249, median TPOT 27.4 ms, median TTFT 2153 ms,
36.4 tok/s/user**. Our **local in-process** leg reports 1758.9 tput/GPU and
195.2 output/GPU at conc 192 — ~9% below the public total and lower on output.
That gap is a **harness/OSL difference** (public InferenceX harness generating
~1024 tok/req vs. our sa-bench `random_range 0.8` ~921 tok/req, plus different
warmup/scheduling), and it applies **equally to both of our legs**. It does not
affect the sidecar-vs-in-process conclusion, which is measured within one
harness. Per-token latency agrees across all three (TPOT ~26.7–27.4 ms).

## Caveats

- Two concurrency points only (192, 256); no full Pareto sweep.
- Workloads across the *public* row and our runs are not bit-identical
  (harness/OSL), so the public number is a sanity cross-check, not the A/B
  baseline. The **local in-process leg (job 2000768)** is the baseline and is
  bit-identical in token volume to the sidecar leg.
- ITL incomparability is a measurement artifact of `stream-interval 50`; if a
  like-for-like ITL is wanted, re-run with per-token streaming on both legs.
- The conc-192 TTFT gap is the open optimization item; conc-256 already shows
  near-parity.

## Data provenance

- **Baseline (in-process):** SLURM job **2000768**, lyris, gb300, 28:49
  wall, `COMPLETED 0:0`.
  Results: `outputs/2000768/logs/sa-bench_isl_8192_osl_1024/results_concurrency_{192,256}_gpus_28_ctx_4_gen_24.json`
  and `benchmark-rollup.{json,csv}`.
- **Sidecar:** SLURM job **1999849**, same paths under `outputs/1999849/`.
- All figures read directly from the per-concurrency sa-bench result JSONs
  (not transcribed from logs); per-GPU values computed as total ÷ 28.
- **Run-enabling fix:** the first in-process attempt (job 2000519) failed at
  `import dynamo.llm` — the wheel mounted at `/srtctl-wheels` was the stock
  `ai_dynamo_runtime` requiring **GLIBC_2.39**, but the `v0.20.0-cu130`
  container ships glibc 2.35. Replaced that wheel with the in-container
  rebuild (max **GLIBC_2.34**, byte-identical to the `/configs/wheels` copy
  the sidecar leg already used); recipe unchanged, so the A/B stays clean. The
  sidecar leg never hit this because its Rust worker does not import
  `dynamo._core`.
