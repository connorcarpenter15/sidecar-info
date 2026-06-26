# TTFT-Tail Isolation — the small-shape high-conc tail is the sidecar worker's response egress

**Date:** 2026-06-12
**Run type:** Mechanism-isolation experiment (not a throughput benchmark). Single
H100 (computelab `ipp2-0177`), **Qwen3-0.6B**, aggregated **c1** path
(`vllm-rs serve` + `dynamo-vllm-sidecar` + `dynamo.frontend`), `--enforce-eager`.
Shape **32×512**, burst concurrencies 1–256.

## Question

The Track B rerun (`benchmark_trackB_rerun_eager_connpool_2026-06-11.md`) showed
the sidecar matches the native backend on throughput/TPOT/stability, with **one
residual cost: a fat TTFT tail at high-concurrency SMALL shapes** (B2 32×512/c128
p99 22.3 s vs 0.72 s). A connection-pool sweep proved that tail is
**pool-independent** (not HTTP/2 head-of-line blocking). This experiment isolates
where the tail actually lives by decomposing TTFT per stage. The tail reproduces
on 0.6B (onset ~c64 vs c16 on 32B — a faster engine pushes onset to higher
concurrency; same phenomenon).

## Method

Client-side TTFT (`vllm bench serve`, through the frontend `:8000`) is compared
against stage-internal measurements that progressively peel back the path:

1. **vllm-rs engine-internal `/metrics`** (`vllm:time_to_first_token_seconds`,
   `request_queue_time_seconds`, `request_prefill_time_seconds`) — measured by
   `vllm-rs`'s `RequestMetricsTracker`, *downstream* of the gRPC+sidecar hop.
2. **Per-request correlation** frontend "request received" → vllm-rs OpenEngine
   handler-entry (`request_id`-keyed) — the inbound transport.
3. **vLLM EngineCore `Running`/`Waiting`** queue depths over the sweep.
4. **A/B vs vllm-rs direct** — same burst hitting `vllm-rs`'s native OpenAI
   server (`:8100`), bypassing frontend+sidecar+gRPC-OpenEngine.
5. **Per-hop sidecar tracing** — `dynamo-vllm-sidecar` instrumented (rebuilt,
   Rust 1.93.1) to log `sc.send` and `sc.first_token elapsed_ms` per `request_id`:
   the round trip [sidecar → gRPC → vllm-rs handler → engine → response-mapping →
   gRPC return → sidecar].
6. **In-process control** — same `dynamo.frontend` + the in-process Python
   `dynamo.vllm` backend (no sidecar / no gRPC), same NATS/SSE response path.

## Results

### 1. Metrics-first: client TTFT explodes, engine-internal TTFT stays tight

| conc | client p99 TTFT (ms) | engine-internal p99 TTFT (ms) | queue/prefill | engine `Waiting` |
|---|---|---|---|---|
| 1 | 45 | 60 | negligible | 0 |
| 8 | 84 | 80 | negligible | 0 |
| 16 | 82 | 60 | negligible | 0 |
| **64** | **6 244** | **80** | negligible | 0 |
| **128** | **8 894** | **80** | negligible | 0 |
| **256** | **10 132** | **250** | negligible | 0 |

EngineCore ran **all** requests concurrently with **`Waiting`=0 at every point**
(Running 256 at c256, KV 21 %, 11 008 tok/s). The engine first-tokens everything
in ≤250 ms; the multi-second tail is entirely outside it.

### 2. Inbound transport is ~0

Per-request `frontend-received → vllm-rs-handler-entry` (correlated by
`request_id`) is **≈0 s at every concurrency**. Requests reach vllm-rs's gRPC
handler immediately; the frontend sends the c256 burst within 0.10 s.

### 3. A/B vs vllm-rs direct — vllm-rs core + the client are clean

| path | c128 p99 TTFT | c256 p99 TTFT |
|---|---|---|
| **A — full c1** (`:8000` → sidecar → gRPC → vllm-rs) | 8 890 ms | 10 164 ms |
| **B — vllm-rs direct** (`:8100`, bypass wrapper) | **158 ms** | **218 ms** |

Same client, same engine, same vllm-rs core — the tail exists **only** through
the Dynamo wrapper.

### 4. Per-hop: the sidecar↔vllm-rs gRPC round trip is fast

Instrumented sidecar, `sc.first_token elapsed_ms` (send → first-token-recv):

| conc | sidecar round-trip p50 | **p99** | max | client p99 TTFT |
|---|---|---|---|---|
| 64 | 58 | **72** | 91 | 6 225 |
| 128 | 70 | **75** | 76 | 8 930 |
| 256 | 93 | **102** | 102 | 10 081 |

Overall (641 requests): p50 73, p99 102, **max 102 ms**. The sidecar receives the
first token back from vllm-rs over gRPC in **≤102 ms at every concurrency**. The
entire 6–10 s tail is **downstream of the sidecar yielding the first token**.

### 5. In-process control — the tail is sidecar-specific

| backend (identical frontend / NATS / SSE) | c128 p99 TTFT | c256 p99 TTFT |
|---|---|---|
| **In-process `dynamo.vllm`** | **360 ms** | **698 ms** |
| **Sidecar (c1)** | 8 930 ms | 10 081 ms |

The in-process backend drives the **same** Dynamo frontend↔backend response path
and is clean. So the generic frontend/NATS/SSE layer is **not** the cause.

## Conclusion

> **SUPERSEDED — see "Follow-up: mechanism redirected" below for the final
> conclusion.** Later experiments (worker-thread sweep, frontend-TTFT split,
> in-process control, and per-request `--save-detailed`) refuted the "sidecar
> worker egress" conclusion in this section. **Final result: the ~10 s "TTFT
> tail" is a benchmark-client (`vllm bench serve`, single asyncio loop)
> SSE read-starvation artifact at 256 concurrent streams — a few connections are
> read only at batch end and drain in one burst (`n_itl=0`, `total=ttft`). It is
> NOT a sidecar serving defect; no sidecar fix is warranted.** The eliminations
> below (engine / inbound / gRPC / vllm-rs core) still hold; the worker delivers
> first chunks to the frontend in ≤470 ms.

The small-shape high-concurrency TTFT tail is **not** in any of: the engine
(`Waiting`=0, ≤250 ms), inbound transport (~0), the OpenEngine gRPC hop +
`vllm-rs` (sidecar round-trip ≤102 ms), `vllm-rs` core or the client (direct
`:8100` clean), or the **generic** Dynamo frontend/NATS/SSE path (in-process
control clean ≤698 ms).

**It is specific to the Rust sidecar worker's response egress** — the path
between `dynamo-vllm-sidecar`'s `LLMEngine::generate` *yielding* the first token
(which happens ≤102 ms after dispatch) and that token reaching the client. Under
many concurrent response streams, first-token forwarding for a few streams
starves to multiple seconds while most stay fast (fat tail: mean stays ~270–400
ms, p99 6–10 s). The likely site is the `dynamo_backend_common` worker runtime's
forwarding of the `LLMEngine` output stream to the frontend (response-stream
polling fairness / NATS egress), which the in-process Python worker does not hit.

**This refutes earlier attributions**, including this benchmark family's own
prior phrasing that the residual cost was a "serialization in the c1 path
(sidecar → vllm-rs OpenEngine server → EngineCore)" — that sub-path is ≤102 ms.
It is also not the gRPC connection multiplexing / HTTP/2 HOL (pool-independent,
shown in the rerun doc). Throughput, TPOT and stability parity are unchanged; the
tail is purely a first-token *delivery* latency-distribution effect in the
sidecar worker's egress, with no effect on throughput or failure rate.

## Fix direction

_(Revised — see the follow-up below. The fix focus moves off the worker egress
and onto the frontend→client SSE-delivery / client-read leg.)_

## Follow-up: mechanism redirected (2026-06-12, later)

Two further experiments moved the conclusion off the worker.

**(a) Worker-thread sweep — scheduling refuted.** Swept the sidecar worker's
tokio runtime threads `DYN_RUNTIME_NUM_WORKER_THREADS` ∈ {4,16,32,64} at
`32×512/c256`. Client p99 TTFT was **flat ~10 s** (10095 / 10128 / 10094 /
10313 ms). If the tail were writer-task scheduling starvation under runtime load,
more threads would shrink it. It doesn't — so it is **not** tokio-scheduling /
CPU-bound, and "more worker threads" is not a fix. Combined with
pool-independence, the tail is independent of both thread count and connection
count.

**(b) Frontend-TTFT split — the tail is the frontend→client leg.** tcpdump was
blocked (no `CAP_NET_RAW` on the shared host net-ns, even as container-root), so
the split used the frontend's own histogram
`dynamo_frontend_time_to_first_token_seconds` (`:8000/metrics`, = dispatch →
first-chunk-received-from-worker) vs client bench TTFT vs vllm-rs engine TTFT
(`:8100`):

| point | client p99 | **frontend p99** | engine p99 | client−frontend (SSE leg) | frontend−engine (worker egress) |
|---|---|---|---|---|---|
| 32×512/c128 | 8908 ms | **470 ms** | 80 ms | **8438 ms** | 390 ms |
| 32×512/c256 | 10032 ms | **470 ms** | 250 ms | **9562 ms** | 220 ms |

The frontend **receives the first chunk from the worker in ≤470 ms (p99)** — the
worker-egress leg is only ~220–390 ms. The entire ~9 s tail is
**`client − frontend` = the frontend→client SSE delivery / client-read leg**, not
the worker, engine, gRPC, or worker egress. This **refutes the "sidecar worker
egress" conclusion above.** All other eliminations (engine, inbound, gRPC,
vllm-rs core) still hold.

**Revised fix direction.** Investigate the **frontend→client first-token
delivery**: the HTTP SSE forwarding of the worker response stream
(`lib/llm/src/http/service`) and how it behaves when the sidecar's many
concurrent streams each begin emitting at nearly the same time. Open questions
to pin next: (1) split frontend-SSE-send vs client-read (frontend has no
SSE-send timestamp metric — needs a small frontend log/metric or a client-side
probe); (2) explain why the in-process backend is clean through the *same*
frontend+bench (re-run the in-process control with `frontend_p99` measured to
confirm apples-to-apples and compare the per-stream emission pattern). Puzzle:
client p99 ≈ batch completion time (~12 s at c256) — a few streams' first tokens
reach the client only near batch end.

**(c) In-process frontend-TTFT control — thundering-herd refuted.** Re-ran the
in-process `dynamo.vllm` backend through the *same* frontend + *same* bench,
measuring both TTFTs. Warm c256 (apples-to-apples): **in-process client p99 =
742 ms (clean)** vs sidecar 10 032 ms; in-process frontend p99 sub-second. (The
in-process c128 = 6284 ms was a first-point cold-start — Triton/compile warmup;
the sidecar tail is ~10 s on warm points too, across 5 consistent runs, so it is
not cold-start.) Since the in-process backend pushes 256 responses through the
*same* frontend + bench with first tokens from the *same* engine (similarly
clustered in time) and the client reads them cleanly at 742 ms, **the bench
client is not the bottleneck for 256 near-simultaneous first-events** — the
thundering-herd idea is refuted (in this round). Next: per-request `--save-detailed`.

**(d) `--save-detailed` per-request data — CONFIRMED: it is a benchmark-client
read-starvation artifact, not a sidecar defect.** `vllm bench serve` accepts
`--save-detailed` (adds per-request `ttfts`, `itls`, `output_lens`). Sidecar c256
per-request breakdown is the smoking gun:

| request class | ttft | out_tok | n_itl | mean_itl | total |
|---|---|---|---|---|---|
| fast (~252 reqs) | ~228 ms | 512 | 512 | 19.6 ms | ~10 260 ms |
| **tail (~4 reqs)** | **~10 260 ms** | 512 | **0** | **0 ms** | **~10 260 ms** |

The tail requests received **nothing for ~10.26 s, then all 512 tokens in a single
burst** (`n_itl = 0`, `total = ttft`); every request finishes at ~10.26 s (batch
completion). So those streams' tokens were **produced on schedule** (buffered in
the socket) but the single-process bench (`vllm bench serve`) event loop — juggling
256 concurrent SSE streams — **never read those few connections until the end**,
then drained each buffered response at once. (A spectrum is visible: some requests
read most tokens then stall for the last ~46.) This **definitively confirms** the
~10 s "TTFT tail" is a **client-side SSE read-starvation measurement artifact**
under single-process 256-stream load — not a sidecar serving regression. The
sidecar delivers first tokens fast (mean ~228 ms) at full streaming rate; a
production deployment with distributed clients cannot hit a single event-loop
bottleneck. **No sidecar fix is warranted.**

Data: `ttft_threadsweep/` (thread sweep), `ttft_frontend/` (frontend split),
`ttft_inproc_fe/` (in-process control), `ttft_savedetailed/` (per-request), on
computelab `/tmp/connorc/`. Scripts: `scripts/trackB/{run_ttft_threadsweep.sh,
run_ttft_frontend.sh, run_ttft_inproc_fe.sh, run_ttft_savedetailed.sh}` +
`analyze_fe.py` + `analyze_detailed.py`.

Data: `ttft_threadsweep/` (thread sweep), `ttft_frontend/` (frontend split),
`ttft_inproc_fe/` (in-process control), on computelab `ipp2-0714`
`/tmp/connorc/`. Scripts: `scripts/trackB/{run_ttft_threadsweep.sh,
run_ttft_frontend.sh, run_ttft_inproc_fe.sh}` + `analyze_fe.py`.

## Data provenance

All on computelab `ipp2-0177`, `/tmp/connorc/`:
- `ttft_results/` — metrics-first sweep (client JSON + `/metrics` before/after).
- `ttft_compare/` — A/B full-path vs vllm-rs-direct.
- `ttft_traced/` — instrumented-sidecar per-hop (`scA.log` has `sc.first_token`).
- `ttft_inproc/` — in-process `dynamo.vllm` control.
- Instrumentation: `dynamo/lib/vllm-sidecar/src/engine.rs` (`sc.send` /
  `sc.first_token elapsed_ms`); rebuilt in `rust:1.93.1` on-node.
- Analysis scripts: `scripts/trackB/{analyze_ttft.py, run_ttft_full.sh,
  run_ttft_compare.sh, run_ttft_traced.sh, run_ttft_inproc.sh}`.
- Companion: `benchmark_trackB_rerun_eager_connpool_2026-06-11.md` (the rerun
  that first flagged the TTFT tail and proved it pool-independent).
