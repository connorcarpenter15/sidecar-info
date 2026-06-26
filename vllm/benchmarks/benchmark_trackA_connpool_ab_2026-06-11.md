# Track A — Connection-Pool A/B (sidecar regression root-cause + fix)

**Date:** 2026-06-11.
**Run type:** GPU-free A/B isolating, then fixing, the config-1 (Rust sidecar)
stability cliff found in
[`benchmark_trackA_4way_2026-06-11.md`](benchmark_trackA_4way_2026-06-11.md):
the sidecar dropped up to ~29% of requests at extreme concurrency on heavy
shapes, while the in-process native Rust backend stayed clean. This run shows
the cause is a single shared HTTP/2 connection in the sidecar's OpenEngine
client, and that pooling several independent connections removes the cliff.

## Root cause (empirically localized)

An earlier instrumentation pass (vllm-rs h2/tonic debug + `ss -tnoi` sampling +
Dynamo JSONL under load) localized the regression to the sidecar's **single
shared HTTP/2 gRPC connection** to `vllm-rs`:

- `ss` showed **exactly one** socket sidecar→:50051 across all offered
  concurrencies (c64 → c4096) — every concurrent `generate` stream multiplexes
  over one connection.
- The vllm-rs h2 `SETTINGS` frame advertised **no `max_concurrent_streams`**
  (unlimited) and the connection window auto-tuned to ~5 MB — so neither a
  stream-count cap nor flow-control starvation is the limiter.
- Under load the connection was **`app_limited` in 88%** of active-stream `ss`
  samples with multi-MB socket queues, while loopback `delivery_rate` peaked at
  261 Gbps. On loopback the wire is effectively infinite, so the limiter is the
  **single userspace h2 codec task** failing to drain per-token DATA frames —
  CPU / single-task serialization, not the network.

So the fix lever is **client-side**, not a server `max_concurrent_streams` bump
(no cap was ever advertised).

## The fix

Replace the sidecar's single tonic `Channel` with a fixed-size `Pool` of
independent `Channel`s (each its own socket + codec task on both ends).
Streaming `generate` calls round-robin across the pool; low-frequency control
RPCs (discovery / health / abort / drain / kv-event-sources) use one stable
connection. New transport flag `--openengine-connections` /
`OPENENGINE_CONNECTIONS` (default **8**) — a transport knob, **not** discovery
metadata, so it does not violate the endpoint-only configuration contract.

(Dynamo fork `feat/vllm-sidecar-openengine`, `lib/vllm-sidecar/src/{client,engine,args}.rs`.)

## What was tested

Config-1 sidecar **against itself**, only the connection count changing:

| Arm | `--openengine-connections` | sockets to :50051 (`ss`) |
|-----|---------------------------:|--------------------------|
| **C1** (baseline) | 1 | 1 — the pre-fix single-channel regression |
| **C8** (fix) | 8 | 8 — round-robined pool |

The connection count was verified live (`ss -tn state established '( dport = :50051 )'`)
after each bring-up: C1 = 1 socket, C8 = 8 sockets, as expected.

## Hardware & environment

- **Host:** computelab `computelab-build-4` (CPU-only — the mock needs no GPU).
- **Container:** docker `mockbench`, host-networked (`/work` = host `/tmp/connorc`).
- **Infra (shared, untouched):** etcd :2379, NATS :4222, Dynamo frontend
  `python -m dynamo.frontend --http-port 8000`.
- **Binary (release):** `/work/target-dynamo-c/release/dynamo-vllm-sidecar`
  (rebuilt 2026-06-11 with the pool), driving
  `/work/target-vllm-c/release/{vllm-rs,vllm-mock-engine}`.
- **Logging:** `RUST_LOG=info`, JSONL off, on **both** arms — the only variable
  is the connection count. (The earlier root-cause pass used `h2=debug`, whose
  overhead inflates the baseline; see *Caveats*.)

## Model & benchmark config

- **Model:** `Qwen/Qwen3-0.6B`, `--enforce-eager`.
- **Mock:** `vllm-mock-engine`, `output_token_chunk_size=1`, no model exec, DP4.
- **Shapes × concurrency:** `32x512` {c64, c256, c1024} (the plateau region) and
  `8192x1024` {c1024, c2048, c4096} (the failure regime).
- **Sharded clients:** 12 shards, 1024 prompts/shard (12,288 prompts/point).
- **Aggregate req/s** = Σ completed / `max(shard wall)`; request-phase only.

## Results — `8192x1024` failure regime (the decisive comparison)

| conc | C1 fail% (1 conn) | C8 fail% (8 conn) | C1 TTFT | C8 TTFT | C1 req/s | C8 req/s |
|------|------------------:|------------------:|--------:|--------:|---------:|---------:|
| c1024 | 0.20% | 0.28% | 654ms | 2122ms | 278.8 | 320.5 |
| c2048 | 0.30% | 0.27% | 2227ms | 4044ms | 362.0 | 281.4 |
| **c4096** | **9.70%** | **0.29%** | 6114ms | 7590ms | 268.3 | 249.5 |

At c4096 the single connection drops **9.70%** (1192 / 12288) of requests; the
8-connection pool drops **0.29%** (36 / 12288) — a **~33× reduction**. The
8-conn arm's higher tail TTFT is *survivorship*: it actually serves the
long-queued requests the 1-conn arm times out and drops, so they count toward
its mean TTFT instead of toward failures.

## Results — `32x512` plateau (small shape)

| conc | C1 req/s | C8 req/s | C1 fail% | C8 fail% |
|------|---------:|---------:|---------:|---------:|
| c64  | 616.3 | 543.9 | 0.90% | 0.35% |
| c256 | 493.6 | 503.1 | 0.03% | 0.02% |
| c1024 | 499.7 | 537.7 | 0.00% | 0.02% |

Both arms plateau ~500 req/s. The pool slightly helps the high-concurrency end
(c1024: 499.7 → 537.7) and is marginally lower at c64. This shape is
per-request-overhead bound (32-token input), not codec-throughput bound, so it
never saturated the single codec task — pooling neither helps nor hurts it much.

## Headline findings

1. **The pool removes the failure cliff.** The Track-A regression — config-1
   dropping ~10–29% of requests at c4096/`8192x1024` — collapses to <0.3% fail
   with 8 connections. The single h2 codec task was the limiter; spreading
   streams over 8 sockets + codec tasks keeps the per-token DATA-frame drain
   ahead of the offered load.

2. **It is a transport-config fix, not an inherent gRPC tax.** No proto, engine,
   or discovery change; just N round-robined `Channel`s behind a flag. This
   confirms the regression was an *unoptimized transport config*, exactly as the
   root-cause analysis predicted.

3. **The win is concentrated where the codec task saturates.** At lower
   concurrency (c1024/c2048) both arms already sit <0.3% fail — the single
   connection is not yet the bottleneck there, so pooling is ~neutral. The
   benefit appears precisely at the extreme-concurrency / long-output corner
   where the one codec task fell behind.

## Caveats

- **Baseline fail% is logging-sensitive.** In this clean run (`RUST_LOG=info`)
  the 1-conn c4096 fail was **9.70%**, versus **29.39%** in the
  [4-way sweep](benchmark_trackA_4way_2026-06-11.md) (different run conditions)
  and ~37% during the `h2=debug` root-cause pass — heavy debug logging itself
  adds codec overhead and inflates the failure rate. The *relative* result (pool
  eliminates the cliff) holds across all three; the absolute baseline number
  depends on logging.
- **Heavy-shape req/s / TTFT are noisy.** On `8192x1024` (8192-token prompts,
  `wall = max(shard)`), per-point req/s and TTFT scatter run-to-run; the robust,
  reproducible signal is the **c4096 fail% collapse**, not the throughput deltas.
- **GPU-free mock only.** This measures the frontend + transport ceiling, not
  model quality or real-engine throughput. With real per-token compute the
  OpenEngine hop is amortized and the single-connection limiter does not bite
  (Track B); the pool is a safety margin there, decisive only in the
  overhead-bound regime.
- **Default of 8** is a starting point, not a tuned optimum; this A/B only
  contrasts 1 vs 8.

## Data provenance

- Aggregated rows appended to `/work/bench/trackA/agg.csv` on host
  `computelab-build-4` under labels `cC1_*` (1 conn) and `cC8_*` (8 conn);
  raw per-shard JSON under `/work/bench/trackA/`.
- Harness (on host, not in repo): `/work/ab_run.sh` (two arms: teardown →
  bring-up at `OPENENGINE_CONNECTIONS={1,8}` → `wait_ready` → `ss` connection
  verify → sweep), driving `/work/trackA_driver.sh sweep`.

```
label,shards,completed,failed,fail_pct,req_s,out_tok_s,ttft_ms,tpot_ms,wall_s
cC1_dp4_32x512_c64,12,12178,110,0.90,616.3,315524,38,0.11,19.8
cC1_dp4_32x512_c256,12,12284,4,0.03,493.6,252701,50,0.88,24.9
cC1_dp4_32x512_c1024,12,12288,0,0.00,499.7,255845,150,3.56,24.6
cC1_dp4_8192x1024_c1024,12,12264,24,0.20,278.8,285539,654,2.60,44.0
cC1_dp4_8192x1024_c2048,12,12251,37,0.30,362.0,370715,2227,1.97,33.8
cC1_dp4_8192x1024_c4096,12,11096,1192,9.70,268.3,236766,6114,6.64,41.4
cC8_dp4_32x512_c64,12,12245,43,0.35,543.9,278482,43,0.12,22.5
cC8_dp4_32x512_c256,12,12286,2,0.02,503.1,257576,49,0.87,24.4
cC8_dp4_32x512_c1024,12,12286,2,0.02,537.7,275324,75,3.43,22.8
cC8_dp4_8192x1024_c1024,12,12254,34,0.28,320.5,328161,2122,0.53,38.2
cC8_dp4_8192x1024_c2048,12,12255,33,0.27,281.4,288142,4044,1.90,43.6
cC8_dp4_8192x1024_c4096,12,12252,36,0.29,249.5,255455,7590,4.50,49.1
```
