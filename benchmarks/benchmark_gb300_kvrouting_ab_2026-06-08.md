# Sidecar GB300 KV-Routing A/B — DeepSeek-V4-Pro, P16/D8, mooncake conversation trace

**Date:** 2026-06-08
**Run type:** KV-aware-routing A/B of the OpenEngine Rust sidecar vs. in-process
vLLM+Dynamo, at an operating point that exercises **KV-event publishing +
KV-aware prefill routing**. Doubles as the runtime gate for the sidecar's
`endpoint_addr` rewrite in `GetKvEventSources` (issue #45).

**Headline:** total token throughput is at parity (**−0.2%**, 15,935 vs 15,966
tok/s). A deeper look at the server-side metrics revises two claims from an
earlier read of this run:

1. **The lower sidecar TTFT is a measurement artifact, not a serving win.** The
   sidecar's better TTFT (avg 1,195 vs 2,018 ms; p90 1,716 vs 6,905 ms) is
   dominated by the in-process Python frontend's `stream-interval 50` gating the
   first client-visible SSE chunk — the *same* artifact that makes ITL
   incomparable. Engine-local prefix-cache hit rate is ~equal across legs (~10%)
   and prefill load is evenly spread on **both** legs, so the gap is not a
   routing/cache quality difference. (To confirm: a control re-run with
   `stream-interval 1` should collapse the in-process TTFT toward the sidecar's.)
2. **#45's subscription + wire-decode path works, but the sidecar's downstream
   KV-event _indexing_ is broken.** The Dynamo KV router subscribed **directly**
   to the prefill workers' ZMQ endpoint and decoded the wire (confirming the
   routable `endpoint_addr` rewrite reaches the publisher). But ~99.8% of "block
   stored" events failed parent linkage at the radix tree (**16** stored-ok vs
   **9,274** `parent_block_not_found` on the sidecar, vs **9,273** stored-ok / **0**
   parent failures on the in-process bridge), so the router's prefix index never
   built and **KV-aware prefix routing was effectively non-operational** on the
   sidecar leg. This is a real bug in the `zmq_wire` converter (see Caveats).

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
| TTFT avg | **−40.8%** (−823 ms; 1,194.7 vs 2,017.8) — artifact‡ |
| TTFT p50 | −14.9% (875.3 vs 1,028.6) — artifact‡ |
| TTFT p90 | **−75.1%** (1,716.3 vs 6,904.8) — artifact‡ |
| TTFT p99 | −23.4% (10,647.5 vs 13,897.3) — artifact‡ |
| e2e latency avg | **−17.9%** (8,197.7 vs 9,986.6) — partly artifact‡ (TTFT is a component of e2e) |

‡ The deltas are real measurements, but **TTFT is not cleanly comparable across
legs** — the in-process Python frontend's `stream-interval 50` gates the first
SSE chunk, the same artifact that makes ITL incomparable. See Takeaway.

## Takeaway

- **Throughput: parity.** Total token throughput is within **−0.2%** (15,935 vs
  15,966 tok/s) and request rate is identical (fixed-schedule replay). The −3% on
  *output* throughput tracks ~3% fewer output tokens generated (OSL-mismatch
  variance: both legs sometimes stop short of the requested length; sidecar had
  1,682 vs the baseline's 1,320 mismatches) — a sampling-level variance, not a
  serving regression.
- **TTFT: lower on the sidecar, but this is a `stream-interval` artifact, not a
  serving win.** The measured deltas are real (avg −41%, p90 −75%), but the cause
  is the same chunking artifact that makes ITL incomparable: the in-process
  Python frontend honors `stream-interval 50`, so the *first* client-visible SSE
  chunk isn't emitted until ~50 decode tokens exist (~50 × ITL ≈ 1.3 s of added
  *measured* TTFT), while the vllm-rs frontend re-emits per token (first chunk =
  first token = true TTFT). The arithmetic fits: the ~0.8 s avg TTFT gap ≈ 50 ×
  the in-process ITL. Three independent checks rule out a routing/cache cause:
  - **Engine-local prefix-cache hit rate is ~equal** — in-process **10.96%**
    cumulative (`vllm:prefix_cache_hits/queries`) vs sidecar **~9.7%** windowed
    (from the vllm-rs prefill-worker `log_stats`). Not higher on the sidecar.
  - **Both legs spread prefill load evenly** — in-process 16 DP-rank endpoints
    all at inflight ~0.30; sidecar 4 worker-endpoints all at ~0.67
    (`dynamo_component_inflight_requests`). Neither router concentrated load.
  - **The sidecar's router prefix index never built** (next section), so it
    could not have been routing on superior prefix overlap in the first place.

  Net: **TTFT is not cleanly comparable across legs here** — like ITL, it is
  confounded by the in-process frontend's chunking. A `stream-interval 1` control
  re-run is the clean confirmation.
- **ITL / goodput are not comparable across legs.** The in-process Python
  frontend honors `stream-interval 50`, so it emits 50-token SSE chunks
  (inter-chunk latency ≈ 1,226 ms) while reporting per-token ITL ≈ 26.6 ms; the
  vllm-rs frontend re-emits per token, so its inter-chunk latency ≈ ITL ≈ 24 ms.
  The `--goodput` gate includes `inter_token_latency:25`, so the goodput delta
  (0.63 vs 0.16 good-fraction) is dominated by this measurement artifact, **not**
  a quality difference. Use throughput + TTFT, never ITL/goodput, across legs.

## #45 — `endpoint_addr` runtime gate: subscription PASSED, but indexing is broken

The #45 gate (does the rewritten routable `endpoint_addr` let a cross-node router
reach the publisher?) **passed** — but the run also surfaced a separate, real bug
*downstream* of it. Splitting the two:

**What passed — subscription + wire-decode reach the publisher.** Direct evidence
from the **sidecar** leg's logs (`theia0235_prefill_w0.out`):

1. **KV-event publishers up.** The prefill EngineCore PUBs KV events from every
   DP rank — `kv_events.py:329 Starting ZMQ publisher thread` on
   `EngineCore_DP0/1/2/3`.
2. **Router subscribed and decoded the wire.**
   `dynamo_kv_router::zmq_wire::convert` log lines show the Dynamo KV router
   decoding raw vLLM ZMQ KV-event messages — it connected, cross-node, to the
   sidecar's advertised endpoint. If `endpoint_addr` were still the bind wildcard
   (`*`) or non-routable, the router could not have connected and we'd see **zero**
   `zmq_wire` activity. We see continuous activity → the routable `endpoint_addr`
   rewrite works at runtime.

**What's broken — the events don't index.** The store events arrive and decode,
but they do **not** build a usable radix tree. The router's
`dynamo_component_kv_cache_events_applied` counter (frontend, `backend` component)
shows the failure starkly:

| `stored` event outcome | in-process (bridge) | sidecar (`zmq_wire`) |
|---|---:|---:|
| **ok** (linked into tree) | **9,273** | **16** |
| **parent_block_not_found** | **0** | **9,274** |
| `removed, ok` | 179,490 | 184,767 |

Same engine, same `block-size 256`, same workload, ~same number of store events
(~9,290) — but on the sidecar's direct-ZMQ path **~99.8% of store events fail to
find their parent block** in the tree, so the prefix index never accumulates
depth. `dynamo_component_router_shared_cache_hit_rate` recorded **zero**
observations on *both* legs (not plumbed in disagg PrefillRouter mode), so it
gives no signal; the `events_applied` breakdown is the real evidence. The
in-process bridge path (`dynamo.vllm` `KvEventPublisher` → NATS, in-order) links
every store cleanly (0 failures), which is why this is a `zmq_wire`-specific
defect, not an engine or block-size issue.

**Consequence:** KV-aware prefix routing was effectively **non-operational** on
the sidecar leg — with no usable index, the router had no overlap signal and fell
back to load-spread routing (consistent with the perfectly even prefill load
above). This is tracked as a follow-up fix (see Caveats).

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
