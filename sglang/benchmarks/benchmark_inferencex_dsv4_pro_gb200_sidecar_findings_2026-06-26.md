# DSV4 Pro GB200 SGLang Sidecar: InferenceX Findings

**Date:** 2026-06-26

**Scope:** DeepSeek-V4-Pro, FP4, 8K input / 1K output, disaggregated Dynamo +
SGLang on GB200 NVL72, regular non-MTP InferenceX topologies.

## Verdict

The OpenEngine SGLang sidecar completed all eight public non-MTP topologies
with 100% request completion and no benchmark failures. Relative to the public
InferenceX rows, total token throughput per GPU stayed between **-4.5% and
+3.6%** at every point. The mean signed difference was **-0.3%**, and the mean
absolute difference was **2.2%**.

This is strong evidence that the sidecar has no broad throughput or decode-
latency regression on the tested DSV4 Pro matrix. It is not a controlled
measurement of sidecar overhead: the exact public SGLang image was unavailable,
so the sidecar used an image 18 days newer. The result should therefore be read
as operational parity with the public curve, not as proof of a sub-percent
OpenEngine cost.

## Comparison Summary

Latency deltas are sidecar relative to public; negative is better. Total
throughput per GPU includes input and output tokens.

| Topology | Concurrency | Sidecar total tok/s/GPU | Throughput delta | Median TTFT delta | Median TPOT delta | Median ITL delta | Completion |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1P8 / 1D8 | 1 | 35 | +3.6% | -7.4% | -3.4% | -0.7% | 10 / 10 |
| 1P8 / 4D8 | 64 | 583 | +3.2% | -8.5% | -1.8% | -1.8% | 640 / 640 |
| 1P8 / 2D16 | 256 | 1,595 | +0.3% | +1.0% | -1.1% | -1.4% | 2,560 / 2,560 |
| 1P8 / 1D16 | 512 | 3,871 | -3.6% | **+20.0%** | -2.2% | -1.8% | 5,120 / 5,120 |
| 2P8 / 1D16 | 1,536 | 6,046 | -4.5% | +1.0% | -0.2% | -0.1% | 15,360 / 15,360 |
| 4P8 / 1D16 | 4,096 | 8,147 | -1.2% | -1.5% | -1.0% | -0.9% | 40,960 / 40,960 |
| 5P8 / 1D16 | 8,192 | 8,824 | +0.4% | +1.0% | -1.5% | -0.7% | 81,920 / 81,920 |
| 6P8 / 1D12 | 8,192 | 9,617 | -0.4% | +2.8% | -0.9% | +0.1% | 81,920 / 81,920 |

## Findings

### 1. Throughput tracks the public curve

All eight rows are inside a 5% band around public. There is no trend toward a
larger sidecar penalty as concurrency, node count, or aggregate throughput
increases:

- The two smallest rows were 3.6% and 3.2% faster than public.
- The largest deficit was 4.5% at C1536; C512 was 3.6% lower.
- The two C8192 rows were within 0.4% of public in opposite directions.
- The highest-throughput row reached **577,003 total tok/s**, or **9,617
  tok/s/GPU**, 0.4% below public.

Given the newer container and single-run measurements, differences this small
should not be assigned to the sidecar itself. The useful conclusion is that no
systematic throughput cliff appeared.

### 2. Decode cadence is at parity or slightly better

Median TPOT was lower in every sidecar row, by 0.2% to 3.4% (1.5% lower on
average). Median ITL was lower in seven rows and only 0.1% higher in the eighth.
P99 TPOT and P99 ITL were also lower in all eight rows; at the two C8192 points,
P99 ITL was 38.5% and 31.3% lower than public.

This rules out an obvious per-token latency tax from the OpenEngine process
boundary. The magnitude of the improvements, especially in tail ITL, may come
from the newer SGLang container and must not be presented as a sidecar speedup.

### 3. Prefill tail latency is the remaining question

Median TTFT was close to public in seven rows, but C512 was **20.0% slower**
(21.66 s versus 18.06 s). P99 TTFT was also higher at C256, C512, C1536, and
C4096 by 21.1%, 17.6%, 17.4%, and 6.7%, respectively. The low-concurrency and
both C8192 tail results were better than public.

The pattern is not monotonic with load and does not coincide with decode
latency degradation, which points more toward prefill queueing or run-to-run
placement variance than a general sidecar bottleneck. C512 is the clearest
repeat target because both its median and P99 TTFT regressed while TPOT and ITL
improved.

### 4. The two C8192 rows expose the intended topology tradeoff

Compared with 5P8 / 1D16, the 6P8 / 1D12 topology delivered:

- 16.8% more total throughput and 9.0% more throughput per GPU;
- 29.5% lower median TTFT; and
- 34.0% higher median TPOT.

The public rows show the same qualitative tradeoff. Moving four GPUs from
decode capacity into additional prefill capacity improves admission and total
system throughput, while making each generated token slower. This behavior is
topology-driven rather than sidecar-specific.

### 5. Reliability was clean

Every parent job completed with exit `0:0`, and SA-Bench completed every planned
request: **228,490 / 228,490** across the matrix. The sidecar attachment,
OpenEngine response path, and result collection remained healthy from 4-node
smoke through the 15-node run. No MTP recipe was submitted.

Some child worker steps show `FAILED 3:0` or `CANCELLED 0:9` after result
collection. These are shutdown artifacts: each parent job completed, wrote its
rollup, and reported the full successful request count.

## Limits

- The sidecar image was
  `lmsysorg/sglang:nightly-dev-cu13-20260615-c127ba64`; public used
  `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`.
- Each sidecar topology has one measured run, so there is no confidence interval
  or direct estimate of run-to-run variance.
- The public API does not expose raw request counts or failure-rate fields.
- Public total throughput was reconstructed from the API's per-GPU metrics.
- Topology, workload, model revision, FP4 precision, Dynamo hash, SGLang
  settings, and non-MTP mode were held to the public recipes.

## Recommendation

Treat this matrix as a successful compatibility and performance gate: there is
no evidence of a release-blocking sidecar penalty. Before making a precise
overhead claim, run a same-image Lyris A/B with sidecar enabled and disabled,
using at least three repeats at C512, C1536, and C8192 6P8 / 1D12. Those rows
cover the TTFT outlier, the largest throughput deficit, and the peak-throughput
configuration. Report medians and ranges, and inspect prefill queue timing if
the C512 TTFT regression repeats.

Keep `SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS=100000` in the benchmark and
production-like sidecar recipes. It prevented the known 300-second OpenEngine
stream timeout from becoming a hidden failure mode under deep queues.

## Artifacts

- [Detailed run report](../../benchmarks/sglang/benchmark_inferencex_dsv4_pro_gb200_sidecar_2026-06-25.md)
- Public recipe commit: `090ecbf7e04fe19c28c2d4ea4576d3189348fb71`
- Sidecar jobs: `2222407`, `2222541`, `2222542`, `2222545`, `2222552`,
  `2222553`, `2222554`, `2222555`
- Recipe directory:
  `/home/connorc/sidecar/srt-slurm-sidecar/recipes/sglang/deepseek-v4-pro-sa-gb200-8k1k-sidecar-diagnostic-20260615/`
