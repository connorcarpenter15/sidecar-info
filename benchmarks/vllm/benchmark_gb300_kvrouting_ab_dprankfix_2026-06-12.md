# Sidecar GB300 KV-Routing A/B (post dp_rank fix) — DeepSeek-V4-Pro, P16/D8, mooncake conversation trace

**Date:** 2026-06-12
**Run type:** Re-run of the [2026-06-08 GB300 KV-routing A/B](./benchmark_gb300_kvrouting_ab_2026-06-08.md)
**after** landing the 3-layer router-forced `dp_rank` passthrough +
`authoritative_dp_rank` KV-event keying fix. The 06-08 run found the sidecar's
KV-event *indexing* was broken (~99.8% `parent_block_not_found`, prefix index
never built, KV-aware routing non-operational). This run asks one question: **did
the dp_rank fix resolve the indexing collapse?**

**Headline:**

1. **Throughput / ITL: parity** — output tok/s within −3%, request rate
   identical (fixed-schedule replay), ITL within −1%. Consistent with 06-08. No
   serving regression.
2. **TTFT: lower on the sidecar (−40%), but this is the known `stream-interval
   50` measurement artifact, NOT a serving win.** Both recipes set decode
   `stream-interval: 50`; the in-process Dynamo worker therefore gates the first
   client-visible SSE chunk by ~50 decode tokens (~50 × ITL ≈ 1.3 s of inflated
   *measured* TTFT), while the sidecar's `vllm-rs` frontend re-emits per token.
   The delta here (1,200 vs 2,011 ms avg) is essentially identical to 06-08
   (1,195 vs 2,018 ms) — same artifact, same magnitude. **Do not read this as a
   sidecar TTFT win.**
3. **KV-routing health: INCONCLUSIVE for this run.** The authoritative metric —
   the frontend's `dynamo_component_kv_cache_events_applied{status}` Prometheus
   counter (stored-ok vs `parent_block_not_found`), which is what made the 06-08
   verdict quantitative — is a **live** counter that was **not scraped during the
   benchmark window** and is gone now that the frontend has exited. From the
   persisted WARN logs the sidecar frontend still emitted **8,683**
   `ParentBlockNotFound` events (vs **0** in-process) — similar in magnitude to
   the pre-fix **9,274** — but successful stores are not logged, so **no
   stored-ok / PBNF *rate* can be derived from this run.** The one positive
   signal: KV events now carry **distinct per-rank `dp_rank` (0–3)** (pre-fix
   they collapsed under one rank), confirming the dp_rank attribution fix
   propagates onto the event plane. But per-rank attribution alone did **not**
   visibly drive PBNF toward zero in the logs. A clean verdict needs a re-run
   with a live `/metrics` scrape (see Follow-ups).

## What was tested

Two legs, **identical** container / Dynamo wheel / model / precision /
parallelism / benchmark, KV-aware routing **on** in both — the only variable is
the Dynamo worker architecture. Same split as the 06-08 run, now with the
dp_rank fix deployed in the sidecar binaries (`configs/bin/{vllm-rs,
dynamo-vllm-sidecar}`).

| Leg | SLURM job | Architecture |
|---|---|---|
| `baseline` (in-process) | **2087115** | `python -m dynamo.vllm` runs the vLLM engine in-process (AsyncLLM) as the Dynamo worker; `kv_role kv_both` |
| `sidecar` | **2087114** | `vllm-rs serve` (Rust frontend + managed Python EngineCore) + `dynamo-vllm-sidecar` Rust worker over **OpenEngine v1 gRPC**; prefill `kv_producer` / decode `kv_consumer`; `openengine_sidecar: true` |

Both legs replay the **same** mooncake conversation trace under fixed-schedule,
so offered load is bit-identical: **9,297 / 9,295** requests sent and **2,734 /
2,736** errored (trace requests whose input exceeds the 16,384-token context —
deterministic, identical across legs → clean apples-to-apples).

## Hardware & environment

- **GPU:** 24× NVIDIA **GB300** (Grace-Blackwell, aarch64), 4 GPU/node, 6 nodes.
- **Topology:** **P16 / D8** — 4 prefill workers TP1×DP4+EP (16 GPU, 4 nodes) +
  1 decode worker TP1×DP8+EP (8 GPU, 2 nodes). The 4-prefill shape is what makes
  KV-aware routing observable (the router has a real choice of prefill
  candidates).
- **Cluster:** lyris, partition `gb300`. Sidecar leg on `theia[0127-0128,
  0130-0131,0137-0138]`; in-process leg on `theia[0222-0223,0225-0228]`.
- **Container:** `vllm/vllm-openai:v0.20.0-cu130` (identical for both legs).
- **Dynamo:** wheel **1.3.0** (identical runtime, HTTP frontend, KV router,
  NATS/etcd for both legs); sidecar binaries carry the 3-layer dp_rank fix.

## Model & engine config

- **Model:** `deepseek-ai/DeepSeek-V4-Pro`, **FP4**, KV cache `fp8`,
  `max-model-len 16384`, `block-size 256`, `trust-remote-code`,
  `enable-expert-parallel`, `moe-backend deep_gemm_mega_moe`,
  `enable-ep-weight-filter`, `enable-sleep-mode`, `tokenizer-mode deepseek_v4`,
  NixlConnector KV transfer.
- **Prefill:** TP1, DP4, EP, `enforce-eager`, `max-num-batched-tokens 16384`,
  `max-num-seqs 16`, `no-async-scheduling`, `safetensors-load-strategy prefetch`,
  `enable-prefix-caching true`.
- **Decode:** TP1, DP8, EP, `max-num-seqs 512`, `max-cudagraph-capture-size 512`,
  `compilation-config {"cudagraph_mode":"FULL_DECODE_ONLY","mode":0}`,
  `no-enable-prefix-caching`, **`stream-interval 50`** (both legs).

## KV-routing config (the variable under test)

- **Frontend:** `router-mode kv`, `router-reset-states true` — the Dynamo KV
  router routes each prefill request to the worker with the best cached-prefix
  overlap, not round-robin.
- **Prefill (KV-event publishers):** `enable-prefix-caching true` +
  `kv-events-config '{"enable_kv_cache_events": true, "publisher": "zmq",
  "endpoint": "tcp://*:5557", "topic": ""}'`. The 4 prefill workers PUB KV-cache
  block events.
  - **In-process:** vLLM EngineCore PUBs per dp_rank; `dynamo.vllm`'s
    `KvEventPublisher` bridges them onto the Dynamo event plane per dp_rank
    (one Dynamo worker per DP rank → naturally per-rank-keyed streams).
  - **Sidecar (fix under test):** the managed EngineCore PUBs per rank; `vllm-rs`
    `GetKvEventSources` advertises one source per DP engine with the per-rank
    port offset and a routable `endpoint_addr`; the Dynamo KV router subscribes
    directly. The **`authoritative_dp_rank`** fix keys each ZMQ source's events
    by its per-socket binding rank (not the constant wire rank an internal-DP
    engine stamps), and the **router-forced `data_parallel_rank`** is threaded
    through OpenEngine `GenerateRequest` so a pinned prefix lands on the same DP
    rank that holds it.
- **Decode:** `no-enable-prefix-caching` (decode never publishes KV events in
  disagg; single DP8 worker, no routing choice).

## Benchmark config (mooncake-router / aiperf)

- **Dataset:** mooncake **conversation** trace, real multi-turn prefix sharing,
  replayed at the trace's own arrival rate (`--fixed-schedule --streaming
  --random-seed 42`).
- **Goodput thresholds:** `time_to_first_token:2000 inter_token_latency:25`.
- **Offered load (identical):** 9,297 / 9,295 requests at **2.62 req/s**, ISL avg
  **5,800 / 5,799** tokens, OSL avg **292 / 301** tokens.

## Results

Aggregate over the 24-GPU deployment (fixed-schedule replay at ~2.62 req/s — not
a saturation sweep).

| leg | req/s | output tok/s | tok/s/user | TTFT avg | TTFT p50 | TTFT p99 | req latency avg | ITL avg | ITL p99 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 2.616 | **788.1** | 38.0 | 2,010.9 | 1,032.3 | 14,189.5 | 9,965.3 | 26.49† | 30.73† |
| sidecar  | 2.619 | **764.0** | 38.4 | 1,200.2 | 919.6 | 9,692.5 | 8,843.5 | 26.25† | 30.66† |

Latencies in ms. † **ITL is not cleanly comparable across legs** — `stream-interval
50` makes the in-process leg emit 50-token chunks; use it only as a coarse parity
check, not a fine comparison.

### Sidecar vs. baseline (deltas)

| metric | Δ (sidecar vs in-process) | read |
|---|---|---|
| request tput | +0.1% (2.619 vs 2.616) | parity (fixed schedule) |
| output tok/s | −3.1% (764.0 vs 788.1) | parity; tracks ~3% fewer output tokens (OSL 292 vs 301) |
| tok/s/user | +1.2% (38.4 vs 38.0) | parity |
| ITL avg | −0.9% (26.25 vs 26.49) | parity |
| TTFT avg | −40.3% (1,200 vs 2,011) | **`stream-interval 50` artifact, not a win** |
| TTFT p99 | −31.7% (9,693 vs 14,189) | artifact |
| req latency avg | −11.3% (8,843 vs 9,965) | partly artifact (TTFT is a component) |
| goodput (good reqs) | +39% (2,741 vs 1,975) | **dominated by the TTFT/ITL artifact via the goodput SLA — not a quality delta** |

## Takeaway

- **Throughput & ITL: parity**, consistent with the 06-08 run. The sidecar does
  not regress serving throughput.
- **TTFT and goodput are not cleanly comparable across legs.** Both are gated by
  the in-process decode `stream-interval 50` (the 06-08 doc establishes this in
  detail). The −40% TTFT and +39% goodput are measurement artifacts of per-token
  vs 50-token-chunk SSE emission, not serving or routing-quality differences.
  A `stream-interval 1` control on both legs is the clean confirmation.
- **Prefix-cache-hit is at parity, but that is NOT routing-health evidence.**
  Engine-local prefill prefix-cache-hit is ~10.3% (sidecar: 10.3/10.1/10.7/10.0%
  across the 4 ranks) vs ~10.4% (in-process: 10.2/10.4/10.6/10.6%). The 06-08 run
  showed this same ~10% parity *even while the router index was fully broken*, so
  equal engine-local cache hit does **not** demonstrate the Dynamo router's
  prefix index is healthy.
- **KV-routing indexing: not validated by this run.** See next section.

## KV-routing health — inconclusive (authoritative counter not captured)

The 06-08 verdict was quantitative because it read the frontend Prometheus
counter `dynamo_component_kv_cache_events_applied{status}`:

| `stored` event outcome | 06-08 in-process | 06-08 sidecar (pre-fix) |
|---|---:|---:|
| ok (linked into tree) | 9,273 | 16 |
| parent_block_not_found | 0 | 9,274 |

**This run did not capture that counter.** It is a live gauge on the frontend's
`:8000/metrics`; the recipe does not scrape it during the benchmark, and the
frontend process has since exited, so the stored-ok value is unrecoverable
post-hoc. What persists in the logs:

- **Sidecar:** **8,683** `ParentBlockNotFound` WARN lines
  (`dynamo_kv_router::indexer …: Failed to find parent block; skipping store
  operation`), each paired with a `Failed to apply event: Some(ParentBlockNotFound)`.
- **In-process:** **0** such lines.
- Successful stores are **not** logged (they lived only in the counter), so
  8,683 cannot be turned into a rate.

Two readings are consistent with the evidence, and this run cannot distinguish
them:

1. **Partial fix:** PBNF dropped from a near-total collapse toward a residual,
   and the surviving 8,683 are a smaller fraction of a now-larger stored-ok
   denominator. The distinct per-rank `dp_rank` in the warnings supports "the
   fix is doing something."
2. **Unfixed linkage:** 8,683 is within ~6% of the pre-fix 9,274, so per-rank
   attribution changed but parent-block linkage is still failing at a similar
   absolute rate (e.g. a within-rank event-ordering / converter issue distinct
   from the rank-collapse the fix targeted).

**The one unambiguous positive:** KV events now carry **distinct `dp_rank`
0–3** under the single sidecar `worker_id` (e.g. `worker_id=7587895488458490439
dp_rank={0,1,2,3}`), where pre-fix they collapsed to one rank. The
`authoritative_dp_rank` keying is reaching the indexer.

## Follow-ups (required for a clean verdict)

1. **Scrape `dynamo_component_kv_cache_events_applied{status}` live** during the
   benchmark window (background `curl :8000/metrics` loop on the frontend node,
   or enable the recipe's metrics capture) so stored-ok vs parent_block_not_found
   is recorded the way 06-08 had it. Without this, the routing-health question
   stays open.
2. **`stream-interval 1` control** on both legs for a like-for-like TTFT/ITL/
   goodput comparison free of the chunking artifact.
3. If PBNF persists with correct per-rank `dp_rank`, investigate within-rank
   event ordering on the direct-ZMQ path (and the startup "Block size must be 4
   tokens" converter reject noted in the 06-08 caveats) as the residual cause.

## Data provenance

- **Baseline (in-process):** SLURM job **2087115**, lyris, gb300, `COMPLETED
  0:0`, elapsed 01:16:20, benchmark duration 3,552.99 s. Rollup
  `outputs/2087115/logs/benchmark-rollup.json`.
- **Sidecar:** SLURM job **2087114**, lyris, gb300, `COMPLETED 0:0`, elapsed
  01:14:32, benchmark duration 3,549.86 s. Rollup
  `outputs/2087114/logs/benchmark-rollup.json`.
- Perf figures from each leg's `benchmark-rollup.json` (`data.<metric>.avg/p50/p99`).
- Prefill prefix-cache-hit from per-worker `*_prefill_w*.out` (`log_stats`).
- PBNF counts from `outputs/2087114/logs/theia0127_frontend_0.out`
  (`dynamo_kv_router::indexer …`); in-process frontend
  `outputs/2087115/logs/theia0222_frontend_0.out` (0 PBNF lines).
- **Gap:** `dynamo_component_kv_cache_events_applied{status}` (stored-ok vs
  parent_block_not_found) was not captured — frontend exited; live counter only.
