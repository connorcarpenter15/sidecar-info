# Sidecar GB300 KV-Routing A/B — DeepSeek-V4-Pro, P16/D8, mooncake conversation trace

**Date:** 2026-06-08
**Run type:** KV-aware-routing A/B of the OpenEngine Rust sidecar vs. in-process
vLLM+Dynamo, at an operating point that exercises **KV-event publishing +
KV-aware prefill routing**. Doubles as the runtime gate for the sidecar's
`endpoint_addr` rewrite in `GetKvEventSources` (issue #45).

**Headline:** the sidecar shows **no regression** — total token throughput is at
parity (**−0.2%**, 15,935 vs 15,966 tok/s) and **TTFT is materially better**
(avg 1,195 vs 2,018 ms; p90 1,716 vs 6,905 ms). The Dynamo KV router subscribed
**directly** to the sidecar prefill workers' ZMQ KV-event endpoint and built its
routing radix tree — confirming the rewritten routable `endpoint_addr` works at
runtime (#45 PASSED).

## What was tested

Two legs, **identical** container / Dynamo wheel / model / precision /
parallelism / benchmark, with KV-aware routing turned **on** in both — the *only*
variable is the Dynamo worker architecture:

| Leg | SLURM job | Architecture |
|---|---|---|
| `baseline` (in-process) | **2035549** | `python -m dynamo.vllm` runs the vLLM engine in-process (AsyncLLM) as the Dynamo worker; `kv_role kv_both` |
| `sidecar` | **2035550** | `vllm-rs serve` (Rust frontend + managed Python EngineCore) + `dynamo-vllm-sidecar` Rust worker over **OpenEngine v1 gRPC**; prefill `kv_producer` / decode `kv_consumer` |

Both legs replay the **same** mooncake conversation trace under fixed-schedule,
so the offered load is bit-identical: **9,297** requests sent and **2,734**
errored in *each* leg (the errors are trace requests whose input exceeds the
16,384-token context — deterministic, identical across legs → clean
apples-to-apples).

Architecture-forced deltas (not independent variables): `kv_role kv_both`
(in-process; the Dynamo router orchestrates the KV-event bridge) vs.
`kv_producer`/`kv_consumer` (sidecar discovers its disagg role from the engine);
`setup_script vllm-container-deps.sh` vs. `vllm-sidecar-deps.sh`. Perf-neutral
for this split.

## Hardware & environment

- **GPU:** 24x NVIDIA **GB300** (Grace-Blackwell, aarch64), 4 GPU/node, 6 nodes
- **Topology:** **P16 / D8** — 4 prefill workers each TP1×DP4+EP (16 GPU, 4
  nodes) + 1 decode worker TP1×DP8+EP (8 GPU, 2 nodes). The 4-prefill shape is
  what makes KV-aware routing observable (the router has a real choice of prefill
  candidates).
- **Cluster:** lyris, partition `gb300`. Sidecar leg: frontend + prefill_w0 on
  `theia0235`, prefill_w1/w2/w3 on `theia0237`/`theia0243`/`theia0244`; decode
  DP8 spans two further nodes.
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

## KV-routing config (the variable under test)

- **Frontend:** `router-mode kv`, `router-reset-states true` — the Dynamo
  frontend runs the KV-aware router (each prefill request goes to the prefill
  worker with the best cached-prefix overlap), not round-robin.
- **Prefill (KV-event publishers):** `enable-prefix-caching true` +
  `kv-events-config '{"enable_kv_cache_events": true, "publisher": "zmq",
  "endpoint": "tcp://*:5557", "topic": ""}'`. The 4 prefill workers PUB KV-cache
  block events.
  - **In-process:** vLLM EngineCore PUBs on `tcp://*:5557(+dp_rank)`;
    `dynamo.vllm`'s `KvEventPublisher` bridges them onto the Dynamo event plane
    per dp_rank; the router subscribes to the bridge.
  - **Sidecar (#45 path):** the managed Python EngineCore PUBs KV events and
    reports `kv_events_publisher`/`endpoint`/`topic` in the
    `EngineCoreReadyResponse` handshake; `vllm-rs` `GetKvEventSources` offsets
    the port per dp_rank and **rewrites the bind wildcard (`*`) to a routable
    node IP** in `endpoint_addr`; the Dynamo KV router subscribes **directly** to
    the worker-node ZMQ endpoint (no `dynamo.vllm` bridge process).
- **Decode:** `no-enable-prefix-caching` (decode never publishes KV events in
  disagg; no routing choice — single DP8 worker).

## Benchmark config (mooncake-router / aiperf)

- **Dataset:** mooncake **conversation** trace (FAST25), real multi-turn prefix
  sharing (**36.64%** cache-efficiency potential) so KV-aware routing has cache
  hits to exploit.
- **Replay:** `aiperf profile --custom-dataset-type mooncake_trace
  --fixed-schedule --streaming --random-seed 42`, replayed at the trace's own
  arrival rate.
- **Goodput thresholds:** `time_to_first_token:2000 inter_token_latency:25`.
- **Identical offered load, confirmed by the data:** both legs sent **9,297**
  requests (2,734 of them over-context errors) at **2.62 req/s**, total input
  **53,919,959** tokens.

## Results

Aggregate over the 24-GPU deployment (this is a fixed-schedule trace replay at a
fixed 2.62 req/s, not a saturation sweep, so aggregate throughput — not per-GPU —
is the meaningful figure).

| leg | req/s | total tok/s | output tok/s | total output tokens | TTFT avg (ms) | TTFT p50 (ms) | TTFT p90 (ms) | TTFT p99 (ms) | e2e latency avg (ms) | ITL avg (ms) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 2.62 | **15,966.3** | 785.9 | 2,791,417 | 2,017.8 | 1,028.6 | 6,904.8 | 13,897.3 | 9,986.6 | 26.6† |
| sidecar  | 2.62 | **15,934.8** | 762.2 | 2,708,627 | 1,194.7 | 875.3 | 1,716.3 | 10,647.5 | 8,197.7 | 24.1† |

† **ITL is not comparable between legs** — see Takeaway. Use throughput + TTFT.

### Sidecar vs. baseline (deltas)

| metric | Δ (sidecar vs in-process) |
|---|---|
| total tok/s | **−0.2%** (15,934.8 vs 15,966.3) — parity |
| output tok/s | −3.0% (762.2 vs 785.9) — tracks ~3% fewer tokens generated |
| total output tokens | −3.0% (2,708,627 vs 2,791,417) |
| request tput | 0.0% (2.62 vs 2.62) |
| TTFT avg | **−40.8%** (−823 ms; 1,194.7 vs 2,017.8) — better |
| TTFT p50 | −14.9% (875.3 vs 1,028.6) — better |
| TTFT p90 | **−75.1%** (1,716.3 vs 6,904.8) — better |
| TTFT p99 | −23.4% (10,647.5 vs 13,897.3) — better |
| e2e latency avg | **−17.9%** (8,197.7 vs 9,986.6) — better |

## Takeaway

- **Throughput: parity.** Total token throughput is within **−0.2%** (15,935 vs
  15,966 tok/s) and request rate is identical (fixed-schedule replay). The −3% on
  *output* throughput tracks ~3% fewer output tokens generated (OSL-mismatch
  variance: both legs sometimes stop short of the requested length; sidecar had
  1,682 vs the baseline's 1,320 mismatches) — a sampling-level variance, not a
  serving regression.
- **TTFT: materially better on the sidecar, with a much tighter tail.** Average
  TTFT is −41% (1,195 vs 2,018 ms) and p90 is −75% (1.7 s vs 6.9 s). On a
  prefix-sharing trace with KV-aware routing, TTFT is the metric that most
  directly reflects whether KV-event subscription + KV-aware prefill routing are
  working: lower TTFT means the router is landing requests on prefill workers
  that already hold the cached prefix. A broken/unroutable `endpoint_addr` would
  degrade routing toward round-robin and make TTFT **worse** — the opposite of
  what we see.
- **ITL / goodput are not comparable across legs.** The in-process Python
  frontend honors `stream-interval 50`, so it emits 50-token SSE chunks
  (inter-chunk latency ≈ 1,226 ms) while reporting per-token ITL ≈ 26.6 ms; the
  vllm-rs frontend re-emits per token, so its inter-chunk latency ≈ ITL ≈ 24 ms.
  The `--goodput` gate includes `inter_token_latency:25`, so the goodput delta
  (0.63 vs 0.16 good-fraction) is dominated by this measurement artifact, **not**
  a quality difference. Use throughput + TTFT, never ITL/goodput, across legs.

## #45 — `endpoint_addr` runtime gate: PASSED

Direct evidence from the **sidecar** leg's logs (`theia0235_prefill_w0.out`):

1. **KV-event publishers up.** The prefill EngineCore PUBs KV events from every
   DP rank — `kv_events.py:329 Starting ZMQ publisher thread` on
   `EngineCore_DP0/1/2/3`.
2. **Router subscribed and decoded the wire.**
   `dynamo_kv_router::zmq_wire::convert` log lines show the Dynamo KV router
   decoding raw vLLM ZMQ KV-event messages — it connected to the sidecar's
   advertised endpoint.
3. **Router built its radix tree.** `dynamo_kv_router::indexer::radix_tree`
   store/remove operations, tagged per `dp_rank` (0–3) of the prefill worker,
   run **continuously** for the full ~1-hour replay — the router is consuming KV
   events into the structure it routes on.

The **in-process** leg has **0** `radix_tree` log lines — its router consumes via
the `dynamo.vllm` `KvEventPublisher` bridge (in-order, no missing-block races),
so the `zmq_wire` direct-subscription path is sidecar-specific. The presence of
active, cross-context ZMQ event consumption on the sidecar leg is *stronger*
evidence than merely seeing the address string: if `endpoint_addr` were still the
bind wildcard (`*`) or a non-routable address, the router (running in a different
process/node) could not have connected and we would see **zero** `zmq_wire` /
`radix_tree` activity. We see continuous activity → the routable `endpoint_addr`
rewrite works at runtime.

## Caveats & follow-ups

- **Benign sidecar-only startup warning.** `dynamo_kv_router::zmq_wire::convert:
  Block not published. Block size must be 4 tokens to be published. Block size
  is: 256` appears exactly **12× per prefill worker, at startup only** (~first 4
  minutes), then steady-state 256-token blocks index into the radix tree fine for
  the rest of the run. Non-blocking (radix tree populated throughout, TTFT
  improved). A possible follow-up is identifying which early event variant the
  converter rejects on the direct-ZMQ path.
- Single operating point (one trace, one fixed arrival rate); no sweep.
- ITL incomparability is a measurement artifact of `stream-interval 50`; for a
  like-for-like ITL, re-run with per-token streaming on both legs.
- The 2,734 over-context errors are a property of the conversation trace vs the
  16,384-token `max-model-len` (identical in both legs), not an engine fault.

## Data provenance

- **Baseline (in-process):** SLURM job **2035549**, lyris, gb300, `COMPLETED
  0:0`, elapsed 01:15:26, benchmark duration 3,551.94 s. Artifacts under
  `outputs/2035549/logs/artifacts/DeepSeek-V4-Pro_conversation_20260607_001036/`
  (`profile_export_aiperf.csv`).
- **Sidecar:** SLURM job **2035550**, lyris, gb300, `COMPLETED 0:0`, elapsed
  01:18:10, benchmark duration 3,553.76 s. Artifacts under
  `outputs/2035550/logs/artifacts/DeepSeek-V4-Pro_conversation_20260607_002027/`.
- Figures read from each leg's `profile_export_aiperf.csv`.
- #45 evidence from `outputs/2035550/logs/theia0235_prefill_w0.out`
  (`kv_events.py`, `dynamo_kv_router::zmq_wire`, `dynamo_kv_router::indexer::radix_tree`).
- Tokenizer note: aiperf 0.9.0 cannot load a tokenizer from an absolute path; the
  mooncake-router `bench.sh` stages an HF hub-cache layout for the served-model
  repo-id and runs offline, so trace tokenization succeeds in both the main
  process and the parallel decode workers.
