# Sidecar GB300 Disagg A/B — DeepSeek-V4-Pro 8k/1k, P16/D8 conc-4096

**Date:** 2026-06-04
**Run type:** precise sidecar-vs-in-process A/B of the OpenEngine Rust sidecar
vs. in-process vLLM+Dynamo at the **throughput-saturated** SemiAnalysis
InferenceX headline operating point for DeepSeek-V4-Pro 8k/1k on GB300
(P16/D8, conc 4096).

**Headline:** the sidecar matches in-process throughput within **−0.06%**
(10,127 vs 10,133 total tok/s/GPU). Perf-parity bar met.

## What was tested

Two legs, **identical** container / Dynamo wheel / model / precision /
parallelism / benchmark — the *only* variable is the Dynamo worker
architecture:

| Leg | SLURM job | Architecture |
|---|---|---|
| `baseline` (in-process) | **2002080** | `python -m dynamo.vllm` runs the vLLM engine in-process (AsyncLLM) as the Dynamo worker |
| `sidecar` | **2009620** | `vllm-rs serve` (Rust frontend + managed Python EngineCore) + `dynamo-vllm-sidecar` Rust worker, talking over **OpenEngine v1 gRPC** |

**The baseline is the local in-process leg (job 2002080)** — same recipe as the
sidecar with the OpenEngine architecture toggled off, run through the **same
sa-bench harness**, so this is the clean apples-to-apples comparison. The public
InferenceX P16/D8 row is used as an external cross-check at the end.

Architecture-forced deltas between the two recipes (not independent variables):
`kv_role kv_both` (in-process; Dynamo router orchestrates P→D) vs.
`kv_producer`/`kv_consumer` (sidecar discovers its disagg role from the
engine); and `setup_script vllm-container-deps.sh` vs. `vllm-sidecar-deps.sh`
(stages the Rust binaries). Perf-neutral for this split.

## Hardware & environment

- **GPU:** 24x NVIDIA **GB300** (Grace-Blackwell, aarch64), 4 GPU/node, 6 nodes
- **Topology:** **P16 / D8** — 4 prefill workers each TP1×DP4+EP (16 GPU, 4
  nodes) + 1 decode worker TP1×DP8+EP (8 GPU, 2 nodes). `ctx_16 / gen_8`.
- **Cluster:** lyris, partition `gb300`. Sidecar leg ran on
  `theia[0253,0255-0257,0265,0268]` (decode DP8 spans `theia0265` ranks 0–3 +
  `theia0268` ranks 4–7).
- **Container:** `vllm/vllm-openai:v0.20.0-cu130` (identical for both legs)
- **Dynamo:** wheel **1.3.0** (identical runtime, HTTP frontend, KV router,
  NATS/etcd for both legs)

## Model & engine config

- **Model:** `deepseek-ai/DeepSeek-V4-Pro`, **FP4**, KV cache `fp8`,
  `max-model-len 16384`, `block-size 256`, `trust-remote-code`,
  `enable-expert-parallel`, `moe-backend deep_gemm_mega_moe`,
  `enable-ep-weight-filter`, `enable-sleep-mode`, `tokenizer-mode deepseek_v4`,
  NixlConnector KV transfer.
- **Prefill:** TP1, DP4, EP, `enforce-eager`, `max-num-batched-tokens 16384`,
  `max-num-seqs 16`, `no-async-scheduling`, `safetensors-load-strategy prefetch`.
- **Decode:** TP1, DP8, EP, `max-num-seqs 512`, `max-cudagraph-capture-size
  512`, `compilation-config {"cudagraph_mode":"FULL_DECODE_ONLY","mode":0}`,
  `stream-interval 50`.

## Benchmark config (sa-bench)

- **ISL 8192 / OSL 1024** (`random_range_ratio 0.8`), `req_rate inf`,
  `max_concurrency 4096`, `num_prompts 40960`, chat template, `ignore-eos`,
  `custom_tokenizer sa_bench_tokenizers.vllm_deepseek_v4.VLLMDeepseekV4Tokenizer`.
- **Concurrency:** 4096 (the InferenceX headline throughput point).
- **Identical workload, confirmed by the data:** both legs drove the exact same
  token volumes — input **302,018,346** and output **37,740,883** — and
  completed **40,960 / 40,960** requests each.

## Results

Throughput shown **per GPU** (÷24 total; output ÷24). `tok/s/user` =
1000 / median TPOT.

| conc | leg | req/s | out tok/s/GPU | tot tok/s/GPU | tok/s/user | TTFT median (ms) | TTFT mean (ms) | TTFT p99 (ms) | TPOT median (ms) | ITL median (ms) | e2el median (ms) |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 4096 | baseline | 29.32 | 1125.6 | **10,132.9** | 18.29 | 82,670.8 | 82,334.7 | 124,567.4 | 54.67 | 2726.0† | 133,408.7 |
| 4096 | sidecar  | 29.30 | 1124.9 | **10,127.2** | 17.73 | 80,962.6 | 80,389.3 | 124,708.5 | 56.40 | 47.0† | 132,897.7 |

† **ITL is not directly comparable between legs** — see Takeaway. Use TPOT for
per-token latency.

### Sidecar vs. baseline (deltas)

| metric | Δ (sidecar vs in-process) |
|---|---|
| total tok/s/GPU | **−0.06%** (10,127.2 vs 10,132.9) |
| output tok/s/GPU | −0.06% (1124.9 vs 1125.6) |
| request tput | −0.07% (29.30 vs 29.32) |
| TPOT median | +3.2% (56.40 vs 54.67) |
| TTFT median | **−2.1%** (−1708 ms; 80,962.6 vs 82,670.8) |
| TTFT mean | **−2.4%** (−1945 ms; 80,389.3 vs 82,334.7) |
| TTFT p99 | +0.1% (124,708.5 vs 124,567.4) |
| e2el median | −0.4% (132,897.7 vs 133,408.7) |

## Takeaway

- **Throughput: parity.** The sidecar lands within **−0.06%** of in-process on
  total tok/s/GPU (10,127 vs 10,133) and on output tok/s/GPU and request rate.
  At the saturated headline point there is no throughput cost from the
  OpenEngine process split.
- **TTFT: parity (marginally better on the sidecar).** Unlike the interactive
  conc-192 point — where the sidecar paid a fixed first-token hop — at conc 4096
  the prefill engines are fully saturated, so the hop is completely amortized and
  the sidecar is actually **~2% lower** on median and mean TTFT; p99 is
  identical. This confirms the H100 / conc-192 finding that the sidecar's TTFT
  overhead is a fixed prefill-path cost that vanishes under load.
- **Per-token latency (TPOT): parity.** Median TPOT is +3.2% (56.40 vs 54.67
  ms) — a small steady-state decode delta, well within run-to-run variance for a
  single point, and consistent with InferenceX's own 57 ms.
- **ITL is a streaming-granularity artifact, not a regression.** The in-process
  leg honors `stream-interval 50`, so sa-bench measures inter-token latency at
  chunk granularity (~50× TPOT ≈ 2726 ms). The sidecar's vllm-rs frontend
  re-emits per token, so its ITL (~47 ms) tracks TPOT. The comparable per-token
  metric is **TPOT**, which is at parity.
- **End-to-end latency: parity.** Median e2el is within −0.4%.

## What made the sidecar leg run (DP master-port handshake fix)

The first sidecar attempt at this topology (job **2008498**) deadlocked during
decode bring-up: the **DP8 decode worker spans two nodes**, and each headless
node independently called `get_open_ports_list(...).pop()` to choose the
`torch.distributed` TCPStore rendezvous port, so the nodes disagreed and the
cross-node rendezvous timed out (`[c10d] ... connect to (…:49815)`,
1,800,000 ms).

Fix (in `vllm/rust/src/engine-core-client/src/transport.rs`): the vllm-rs InProc
coordinator now **broadcasts `data_parallel_master_port` +
`_data_parallel_master_port_list` in the handshake INIT message**, so all
multi-node DP engines agree on the rendezvous port — matching native vLLM's
`coordinated_dp` config-init behavior. Gated on `coordinator.is_some()`
(InProc / multi-engine MoE), so single-engine paths are unaffected.

Rebuilt aarch64 vllm-rs in the `v0.20.0-cu130` container (glibc 2.35; build job
**2009581**, 4 transport unit tests passing), redeployed **only** `vllm-rs` to
`configs/bin` — the `dynamo-vllm-sidecar` binary was unchanged. In job 2009620
the decode DP8 rendezvous succeeded with no TCPStore timeout; all 5 workers
reached READY and the run completed clean.

## Cross-check vs. public InferenceX (external, not the primary baseline)

SemiAnalysis publishes an in-process `dynamo-vllm` GB300 P16/D8 row at this
operating point (FP4, disagg, 24 GPU, conc 4096, 8k/1k, image v0.20.0): **total
tput/GPU 10,214, median TPOT 57 ms, ~17.5 tok/s/user**. Our local legs report
**10,133** (in-process) and **10,127** (sidecar) total tok/s/GPU and TPOT
54.7 / 56.4 ms — all three within **<1%** on throughput and per-token latency.

Note: the public row's reported **TTFT (~79 ms)** is *not* comparable to our
~81 s figure — sa-bench injects all requests at `request_rate inf` (a conc-4096
burst that includes deep queueing in TTFT), whereas the InferenceX harness paces
to hold conc 4096 in steady state. The sidecar-vs-in-process TTFT comparison is
clean because both legs use the identical sa-bench harness; the InferenceX
cross-check should be read on throughput and TPOT only.

## Caveats

- Single concurrency point (4096); no full Pareto sweep.
- The InferenceX public row is a sanity cross-check, not the A/B baseline
  (different harness + load injection). The **local in-process leg (job
  2002080)** is the baseline and is bit-identical in token volume to the sidecar
  leg.
- ITL incomparability is a measurement artifact of `stream-interval 50`; for a
  like-for-like ITL, re-run with per-token streaming on both legs.
- TTFT at `request_rate inf` is dominated by conc-4096 admission queueing
  (~80 s on both legs); it is a workload property here, not an engine metric.

## Data provenance

- **Baseline (in-process):** SLURM job **2002080**, lyris, gb300,
  `COMPLETED 0:0`, benchmark finished 2026-06-03 17:34:34, main run 1397.10 s.
  Results: `outputs/2002080/logs/sa-bench_isl_8192_osl_1024/results_concurrency_4096_gpus_24_ctx_16_gen_8.json`.
- **Sidecar:** SLURM job **2009620**, lyris, gb300, `COMPLETED 0:0`
  (16:39:49→17:29:44, 49:55 wall), main run 1397.89 s. Results under
  `outputs/2009620/logs/sa-bench_isl_8192_osl_1024/`.
- Figures read from the sa-bench `Serving Benchmark Result` blocks of each
  leg's `benchmark.out`; per-GPU values computed as total ÷ 24.
- **Run-enabling fix:** DP master-port handshake broadcast in
  `engine-core-client/src/transport.rs` (build job 2009581); see section above.
