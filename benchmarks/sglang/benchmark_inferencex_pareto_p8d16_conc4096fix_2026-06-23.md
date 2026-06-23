# InferenceX Pareto (SGLang) — P8/D16 DeepSeek-R1-FP4, and the conc-4096 fix

**Dates:** 2026-06-16 (first full sweep) → 2026-06-22/23 (conc-4096 root-cause +
fix + verification). SGLang counterpart to the vLLM GB300 InferenceX work
(`benchmark_gb300_disagg_ab_p16d8_c4096_2026-06-04.md`).

## Goal

Run the InferenceX-style concurrency sweep for the **SGLang OpenEngine sidecar**
at a 24-GPU disaggregated P/D topology and compare to the in-process
`dynamo.sglang` worker on the **identical** recipe/cluster — isolating the
OpenEngine gRPC process boundary, the same question the vLLM Track B answered.

- **Model:** DeepSeek-R1-FP4 (`modelopt_fp4`, `trtllm_mla`, `fp8_e4m3` KV).
- **Topology:** P8/D16 = 2 prefill nodes (tp4 each, 8 GPU) + 1 decode instance
  over 4 nodes (tp16/dp16/ep16 wide-EP DeepEP `low_latency`, dp-attention, 16 GPU).
- **Workload:** 8k ISL / 1k OSL, sa-bench, concurrency sweep 512 / 2048 / 4096,
  `req_rate` 700.
- **Cluster:** ptyche GB200, container `sglang-runtime:0.8.0` (sglang 0.5.6.post2).
- **A/B:** sidecar (`dynamo-sglang-sidecar` → OpenEngine gRPC → overlaid
  `openengine_server.py` + `_core` on the container sglang) vs in-process
  (`python -m dynamo.sglang`, same recipe minus `setup_script` + `openengine_sidecar`).

There is **no public InferenceX P8/D16 GB200 dynamo-sglang row** (the public
topologies are 4/16, 8/8, 4/4, 24/48, 40/32, 48/24, 72/72), so the in-process
control is the apples-to-apples baseline.

## Result: clean sidecar/in-process parity across the full sweep

Per-GPU = total token throughput ÷ 24. `tot/gpu` = input+output tok/s/GPU.

| conc | sidecar tot/gpu | in-proc tot/gpu | **sidecar / in-proc** | medTPOT (side ≈ in-proc) | completion |
|------|----------------:|----------------:|:---------------------:|:------------------------:|:----------:|
| 512  | 4041 | 3845 | **105.1%** | 20.15 ≈ 20.20 ms | 5120/5120 both |
| 2048 | 3672 | 3712 | **98.9%**  | 20.03 ≈ 20.00 ms | 20480/20480 both |
| 4096 | 3662 | 3833 | **95.5%**  | 20.37 ≈ 20.06 ms | 40960/40960 both |

TPOT is identical (~20 ms) at every point — the gRPC hop costs nothing on
sustained throughput or per-token latency. conc 4096 required the two fixes below;
512 and 2048 were clean from the first sweep.

Jobs: sidecar sweep `2273108` (conc 512/2048), in-process control `2273121`
(all three), fixed conc-4096 sidecar `2275001`.

## The conc-4096 investigation (three wrong turns, then the fix)

The first full sweep showed conc 4096 collapsing: only **3706/40960 (9%)**
completed, **42 433** frontend `PrefillError("...returned error in output:
unknown error")`, and median/​p99 TTFT cliffing at **298 s ≈ 5 min**.

### Red herring 1 — connection pooling (job 2273766)

The sidecar gRPC client *already* pools (`lib/sglang-sidecar/src/client.rs`
`Pool`, round-robin `stream_client`; `--openengine-connections`/
`OPENENGINE_CONNECTIONS`, default 8 — confirmed `connections=8` in the log).
Bumping to **32** produced an **identical** result (3728/40960, p99 TTFT 298 s).
Pooling is not the lever.

### Root cause — the OpenEngine server response timeout (job 2274087)

The Rust OpenEngine server has a per-stream `response_timeout_secs` default of
**300 s** (`rust/sglang-grpc/src/lib.rs`), and `openengine_server.py` called
`start_openengine_server(...)` without overriding it. Under conc-4096 prefill
over-subscription, any request waiting >300 s for its first chunk was killed →
`PrefillError`. In-process has no per-request server timeout (p99 TTFT 458 s) so
it completes all 40960.

**Fix 1 (sglang fork, Python-only — the Rust server already accepts the param):**
`openengine_server.py` now reads `SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS`
(default 300) and passes `response_timeout_secs=` through. Set to **100000** in
the recipe (matching the existing `SGLANG_DISAGGREGATION_*_TIMEOUT`). Committed:
`fix(openengine): harden sidecar disaggregation bridge`.

Result: `PrefillError` dropped **42433 → 0** and the conc-4096 warmup completed
8192/8192. But the **main run then OOMed**: all 4 decode nodes hit
`token_usage 1.00` → `RuntimeError: Decode out of memory` → `deep_gemm`
CUDA assertion → **Xid 31** on the decode node; job FAILED, no result.

### Second limit — decode KV exhaustion (the headroom fix)

Removing the 300 s shedding valve let the unbounded conc-4096 queue exhaust the
decode KV. Comparing the in-process control and the OOM'd sidecar showed they
admit decode requests **near-identically** (both `token_usage 1.00`, prealloc
255 vs 276, retract 5 vs 6) — there is **no admission-backpressure gap to
replicate**. The sidecar simply runs ~8% hotter on KV residency (the gRPC
response hop holds decode KV slightly longer) and tipped over a latent OOM edge
that in-process barely survived.

The crash was in `alloc_for_decode` (a decode *step* finding 0 free tokens). The
disagg prealloc gate reserves `num_reserved_decode_tokens × n_active` of headroom
(`python/sglang/srt/disaggregation/decode.py` `_active_reserved_tokens` /
`_allocatable_token_budgets`). The recipe's `num-reserved-decode-tokens = 112`
was too thin.

**Fix 2 (recipe config):** raise decode `num-reserved-decode-tokens` **112 → 512**
(SGLang's default) for KV headroom.

### Verification (job 2275001)

With both fixes (`SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS=100000` +
`num-reserved-decode-tokens=512`, connections back at the default 8):

| metric | fixed sidecar (2275001) | in-process (2273121) | old sidecar 300s (2273108) |
|---|---:|---:|---:|
| completed | **40960 (100%)** | 40960 (100%) | 3706 (9%) |
| tot tok/s/GPU | 3662 (**95.5%** of in-proc) | 3833 | 424 |
| median TPOT | 20.37 ms | 20.06 ms | 20.23 ms |
| median / p99 TTFT | 354 s / 489 s | 347 s / 459 s | 154 s / 298 s |
| PrefillError | **0** | 0 | 42433 |
| decode OOM | **0** | 0 | crash (Xid 31) |
| peak KV usage | **0.95** | 1.00 | 1.00 (OOM) |

## Takeaways

1. The SGLang OpenEngine sidecar reaches **clean parity** (95–105% of in-process,
   identical TPOT) with the in-process `dynamo.sglang` worker for DeepSeek-R1-FP4
   disagg P8/D16 8k/1k across the full concurrency sweep.
2. The conc-4096 collapse was **not** a sidecar code flaw and **not** connection
   pooling. It was two latent tuning edges the sidecar's slightly-higher KV
   residency was first to expose:
   - the OpenEngine server's 300 s per-stream response timeout (shed requests),
   - the aggressive `num-reserved-decode-tokens=112` decode headroom (OOM).
3. Both belong in the production sidecar recipe: set
   `SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS` (≈ the SGLang disagg timeouts) and
   `num-reserved-decode-tokens: 512`.
4. conc 4096 at 8k/1k on a 16-GPU decode is the over-saturated tail (minutes-long
   TTFT for both sidecar and in-process); the useful operating points are conc
   512/2048, where the sidecar was clean from the start.
