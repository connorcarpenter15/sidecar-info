# InferenceX DSV4 Pro GB200 SGLang Sidecar Benchmark

**Status, 2026-06-26 18:55 PDT:** all eight non-MTP public-topology rows
completed on Lyris with the closest working SGLang container found. No MTP
recipes were run or included in the comparison.

This run is **diagnostic-only versus the public InferenceX container** because
the exact public image `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`
was not available on Lyris. The recipes preserve the public non-MTP topology,
load, model, Dynamo hash, SGLang config, and benchmark parameters.

## Locked Public Target

- Model: `deepseek-ai/DeepSeek-V4-Pro`
- Model revision from Lyris cache:
  `45040942eb0d1c4e29fa6b92a6195f110e9e7444`
- Workload: 8K input / 1K output
- Precision: FP4
- Hardware: GB200 NVL72
- Backend: Dynamo + SGLang
- Mode: disaggregated
- Spec decoding: non-MTP regular entry only
- Public container:
  `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`
- Dynamo hash: `92f5b3b8d7dd5ab9179d4b1034bd2c1c0803693e`
- Benchmark: `sa-bench`, `isl: 8192`, `osl: 1024`, `req_rate: inf`,
  `use_chat_template: false`
- Public recipe source commit:
  `090ecbf7e04fe19c28c2d4ea4576d3189348fb71`
- Public recipe path:
  `benchmarks/multi_node/srt-slurm-recipes/sglang/deepseek-v4/8k1k`

## Implemented Recipes

Local diagnostic recipe directory:

`/home/connorc/sidecar/srt-slurm-sidecar/recipes/sglang/deepseek-v4-pro-sa-gb200-8k1k-sidecar-diagnostic-20260615/`

All eight non-MTP recipes exist, and no `*mtp*.yaml` files are present.

Recipe-wide sidecar-only deltas:

- `setup_script: sglang-sidecar-deps.sh`
- `backend.openengine_sidecar: true`
- `backend.sidecar_binary: "dynamo-sglang-sidecar"`
- `SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS: "100000"`
- Sidecar artifact mount:
  `/lustre/fsw/coreai_dlfw_dev/connorc/sidecar-artifacts:/sidecar-artifacts`
- Benchmark tokenizer:
  `sa_bench_tokenizers.sglang_deepseek_v4.SGLangDeepseekV4Tokenizer`

## Container Selection

Requested public image:

- `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`
- Availability: not found in the staged Lyris container locations checked.

Rejected closer image:

- `docker.io/lmsysorg/sglang:nightly-dev-cu13-20260518-c67b2870`
- Lyris SquashFS:
  `/lustre/fsw/coreai_dlfw_dev/shuw/dsv4/srt-slurm/lmsysorg+sglang+nightly-dev-cu13-20260518-c67b2870.sqsh`
- Probe: CUDA available, `torch.cuda.device_count() == 4`
- Smoke result: failed during benchmark with decode-side CUDA illegal memory
  access in job `2214437`.

Selected diagnostic image:

- `docker.io/lmsysorg/sglang:nightly-dev-cu13-20260615-c127ba64`
- Lyris SquashFS:
  `/lustre/fsw/coreai_dlfw_dev/shuw/dsv4/srt-slurm/lmsysorg+sglang+nightly-dev-cu13-20260615-c127ba64.sqsh`
- CUDA probe job: `2222404`
- Probe result: `torch.__version__ == 2.11.0+cu130`,
  `torch.version.cuda == 13.0`, `torch.cuda.is_available() == True`,
  `torch.cuda.device_count() == 4`
- SGLang probe job: `2222405`
- SGLang version: `0.0.0.dev1+gc0dfe4c8e`

## Run Matrix

| Recipe | Public topology | Concurrency | Job | Current state | Classification |
|---|---|---:|---:|---|---|
| `disagg-gb200-1p1d-tp8-tp8-4-c1.yaml` | 1 prefill worker x 8 GPUs, 1 decode worker x 8 GPUs | 1 | `2222407` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-1p4d-dep8-tp8-10-c64.yaml` | 1 prefill worker x 8 GPUs, 4 decode workers x 8 GPUs | 64 | `2222541` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-1p2d-dep8-dep16-10-c256.yaml` | 1 prefill worker x 8 GPUs, 2 decode workers x 16 GPUs | 256 | `2222542` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-1p1d-dep8-dep16-6-c512.yaml` | 1 prefill worker x 8 GPUs, 1 decode worker x 16 GPUs | 512 | `2222545` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-2p1d-dep8-dep16-8-c1536.yaml` | 2 prefill workers x 8 GPUs, 1 decode worker x 16 GPUs | 1536 | `2222552` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-4p1d-dep8-dep16-12-c4096.yaml` | 4 prefill workers x 8 GPUs, 1 decode worker x 16 GPUs | 4096 | `2222553` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-5p1d-dep8-dep16-14-c8192.yaml` | 5 prefill workers x 8 GPUs, 1 decode worker x 16 GPUs | 8192 | `2222554` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |
| `disagg-gb200-6p1d-dep8-dep12-15-c8192.yaml` | 6 prefill workers x 8 GPUs, 1 decode worker x 12 GPUs | 8192 | `2222555` | `COMPLETED`, exit `0:0` | exact public topology, diagnostic-only container |

Output directories:

- `2222407`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222407`
- `2222541`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222541`
- `2222542`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222542`
- `2222545`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222545`
- `2222552`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222552`
- `2222553`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222553`
- `2222554`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222554`
- `2222555`: `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222555`

## Public Baseline Snapshot

Source: live InferenceX API query on `2026-06-26`:

`https://inferencex.semianalysis.com/api/v1/benchmarks?model=DeepSeek-V4-Pro`

Filter applied: `hardware == gb200`, `framework == dynamo-sglang`,
`precision == fp4`, `spec_method == none`, `disagg == true`,
`isl == 8192`, `osl == 1024`.

Public run:

- Date: `2026-06-12`
- Run URL:
  `https://github.com/SemiAnalysisAI/InferenceX/actions/runs/27404532035/attempts/1`
- Image: `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`

The API exposes throughput per GPU; total public throughput below is computed as
`tput_per_gpu * (num_prefill_gpu + num_decode_gpu)`, and public output throughput
is computed as `output_tput_per_gpu * num_decode_gpu`.

| Row | GPUs | Decode GPUs | Output tok/s | Total tok/s | Total tok/s/GPU | Median TTFT ms | Median TPOT ms | Median ITL ms | P99 TTFT ms | P99 TPOT ms | P99 ITL ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C1 | 16 | 8 | 60.884 | 545.002 | 34.063 | 937.701 | 14.846 | 14.443 | 2893.461 | 15.299 | 18.952 |
| C64 | 40 | 32 | 2509.864 | 22623.353 | 565.584 | 2872.608 | 19.053 | 18.936 | 27434.047 | 19.529 | 21.144 |
| C256 | 40 | 32 | 7069.384 | 63606.160 | 1590.154 | 11140.995 | 20.345 | 1219.078 | 32685.468 | 20.899 | 1332.803 |
| C512 | 24 | 16 | 10709.345 | 96384.879 | 4016.037 | 18055.208 | 23.180 | 1384.627 | 41373.945 | 23.429 | 1438.559 |
| C1536 | 32 | 16 | 22517.394 | 202547.340 | 6329.604 | 31133.312 | 27.585 | 1649.985 | 62063.868 | 28.213 | 1856.698 |
| C4096 | 48 | 16 | 43968.760 | 395805.648 | 8245.951 | 45655.193 | 31.870 | 1903.526 | 102165.446 | 32.879 | 2843.184 |
| C8192 5p1d | 56 | 16 | 54653.350 | 491938.283 | 8784.612 | 79385.700 | 38.195 | 2254.396 | 217154.165 | 43.433 | 6730.431 |
| C8192 6p1d | 60 | 12 | 64361.999 | 579326.448 | 9655.441 | 54971.221 | 50.904 | 2999.515 | 162027.564 | 54.642 | 6382.019 |

## Smoke Result

Smoke job `2222407` validated server startup, sidecar OpenEngine attachment,
endpoint verification, benchmark execution, and result collection.

- Nodes: `lyris[0274,0281,0283,0285]`
- Start: `2026-06-26T15:56:17`
- End: `2026-06-26T16:13:31`
- Elapsed: `00:17:14`
- Health gate: passed at `2026-06-26 16:09:17 PDT`
- Identity verified: model revision `45040942eb0d`, Dynamo `1.2.0`,
  SGLang `0.0.0.dev1+gc0dfe4c8e`
- Completed requests: 10 / 10
- Request throughput: 0.067807 req/s
- Output throughput: 63.080988 tok/s
- Total token throughput: 564.670794 tok/s
- Total token throughput per GPU: 35.292 tok/s/GPU
- Mean TTFT: 1414.191 ms
- Median TTFT: 868.415 ms
- P99 TTFT: 2802.561 ms
- Mean TPOT: 14.347 ms
- Median TPOT: 14.347 ms
- P99 TPOT: 14.352 ms
- Mean ITL: 14.332 ms
- Median ITL: 14.338 ms
- P99 ITL: 14.490 ms
- Mean E2EL: 14747.099 ms
- Median E2EL: 14775.486 ms
- P99 E2EL: 16969.127 ms

Smoke artifacts:

- Rollup JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222407/logs/benchmark-rollup.json`
- Rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222407/logs/benchmark-rollup.csv`
- SA-Bench result JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222407/logs/sa-bench_isl_8192_osl_1024/results_concurrency_1_gpus_16_ctx_8_gen_8.json`

## Completed Sidecar Results

These rows are diagnostic-only versus the public container, but preserve the
public topology and load.

| Concurrency | Job | GPUs | Decode GPUs | Completed requests | Output tok/s | Total tok/s | Req/s | Median TTFT ms | Median TPOT ms | Median ITL ms | P99 TTFT ms | P99 TPOT ms | P99 ITL ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | `2222407` | 16 | 8 | 10 | 63.081 | 564.671 | 0.0678 | 868.415 | 14.347 | 14.338 | 2802.561 | 14.352 | 14.490 |
| 64 | `2222541` | 40 | 32 | 640 | 2589.182 | 23338.312 | 2.8090 | 2627.175 | 18.713 | 18.587 | 26364.260 | 18.940 | 20.760 |
| 256 | `2222542` | 40 | 32 | 2560 | 7089.087 | 63783.441 | 7.6884 | 11257.966 | 20.117 | 1202.281 | 39596.618 | 20.619 | 1278.934 |
| 512 | `2222545` | 24 | 16 | 5120 | 10322.232 | 92900.835 | 11.1939 | 21662.756 | 22.676 | 1360.001 | 48673.160 | 23.190 | 1406.800 |
| 1536 | `2222552` | 32 | 16 | 15360 | 21507.555 | 193463.694 | 23.3253 | 31429.309 | 27.539 | 1648.613 | 72891.510 | 27.890 | 1700.190 |
| 4096 | `2222553` | 48 | 16 | 40960 | 43440.274 | 391048.239 | 47.1457 | 44966.327 | 31.557 | 1885.638 | 108994.210 | 32.170 | 2412.810 |
| 8192 | `2222554` | 56 | 16 | 81920 | 54899.268 | 494151.809 | 59.5707 | 80181.815 | 37.628 | 2239.438 | 214411.330 | 39.800 | 4142.120 |
| 8192 | `2222555` | 60 | 12 | 81920 | 64103.849 | 577002.828 | 69.5585 | 56536.043 | 50.424 | 3003.640 | 159326.960 | 52.030 | 4384.950 |

Completed result artifacts:

- `2222541` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222541/logs/benchmark-rollup.csv`
- `2222541` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222541/logs/sa-bench_isl_8192_osl_1024/results_concurrency_64_gpus_40_ctx_8_gen_32.json`
- `2222542` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222542/logs/benchmark-rollup.csv`
- `2222542` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222542/logs/sa-bench_isl_8192_osl_1024/results_concurrency_256_gpus_40_ctx_8_gen_32.json`
- `2222545` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222545/logs/benchmark-rollup.csv`
- `2222545` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222545/logs/sa-bench_isl_8192_osl_1024/results_concurrency_512_gpus_24_ctx_8_gen_16.json`
- `2222552` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222552/logs/benchmark-rollup.csv`
- `2222552` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222552/logs/sa-bench_isl_8192_osl_1024/results_concurrency_1536_gpus_32_ctx_16_gen_16.json`
- `2222553` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222553/logs/benchmark-rollup.csv`
- `2222553` rollup JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222553/logs/benchmark-rollup.json`
- `2222553` benchmark log:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222553/logs/benchmark.out`
- `2222553` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222553/logs/sa-bench_isl_8192_osl_1024/results_concurrency_4096_gpus_48_ctx_32_gen_16.json`
- `2222554` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222554/logs/benchmark-rollup.csv`
- `2222554` rollup JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222554/logs/benchmark-rollup.json`
- `2222554` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222554/logs/sa-bench_isl_8192_osl_1024/results_concurrency_8192_gpus_56_ctx_40_gen_16.json`
- `2222555` rollup CSV:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222555/logs/benchmark-rollup.csv`
- `2222555` rollup JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222555/logs/benchmark-rollup.json`
- `2222555` SA-Bench JSON:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2222555/logs/sa-bench_isl_8192_osl_1024/results_concurrency_8192_gpus_60_ctx_48_gen_12.json`

## Public Comparison

All comparison rows preserve the public topology and load. They are
diagnostic-only versus the public InferenceX container because the public
`20260528-0abe6a85` image was not available on Lyris and the closest working
container was `20260615-c127ba64`.

Throughput comparison:

| Row | Sidecar output tok/s | Public output tok/s | Output delta | Sidecar total tok/s/GPU | Public total tok/s/GPU | GPU delta |
|---|---:|---:|---:|---:|---:|---:|
| C1 | 63.081 | 60.884 | +3.6% | 35.292 | 34.063 | +3.6% |
| C64 | 2589.182 | 2509.864 | +3.2% | 583.458 | 565.584 | +3.2% |
| C256 | 7089.087 | 7069.384 | +0.3% | 1594.586 | 1590.154 | +0.3% |
| C512 | 10322.232 | 10709.345 | -3.6% | 3870.868 | 4016.037 | -3.6% |
| C1536 | 21507.555 | 22517.394 | -4.5% | 6045.740 | 6329.604 | -4.5% |
| C4096 | 43440.274 | 43968.760 | -1.2% | 8146.838 | 8245.951 | -1.2% |
| C8192 5p1d | 54899.268 | 54653.350 | +0.4% | 8824.139 | 8784.612 | +0.4% |
| C8192 6p1d | 64103.849 | 64361.999 | -0.4% | 9616.714 | 9655.441 | -0.4% |

Latency comparison:

| Row | Sidecar median TTFT ms | Public median TTFT ms | TTFT delta | Sidecar median TPOT ms | Public median TPOT ms | TPOT delta | Sidecar median ITL ms | Public median ITL ms | ITL delta |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| C1 | 868.415 | 937.701 | -7.4% | 14.347 | 14.846 | -3.4% | 14.338 | 14.443 | -0.7% |
| C64 | 2627.175 | 2872.608 | -8.5% | 18.713 | 19.053 | -1.8% | 18.587 | 18.936 | -1.8% |
| C256 | 11257.966 | 11140.995 | +1.0% | 20.117 | 20.345 | -1.1% | 1202.281 | 1219.078 | -1.4% |
| C512 | 21662.756 | 18055.208 | +20.0% | 22.676 | 23.180 | -2.2% | 1360.001 | 1384.627 | -1.8% |
| C1536 | 31429.309 | 31133.312 | +1.0% | 27.539 | 27.585 | -0.2% | 1648.613 | 1649.985 | -0.1% |
| C4096 | 44966.327 | 45655.193 | -1.5% | 31.557 | 31.870 | -1.0% | 1885.638 | 1903.526 | -0.9% |
| C8192 5p1d | 80181.815 | 79385.700 | +1.0% | 37.628 | 38.195 | -1.5% | 2239.438 | 2254.396 | -0.7% |
| C8192 6p1d | 56536.043 | 54971.221 | +2.8% | 50.424 | 50.904 | -0.9% | 3003.640 | 2999.515 | +0.1% |

Completion and failure-rate comparison:

- Sidecar rows: all completed with parent SLURM exit `0:0`; SA-Bench successful
  requests matched planned prompts for every row, so completion rate is `100%`
  and benchmark failure rate is `0%`.
- Public rows: the InferenceX API and compact public artifacts expose successful
  aggregate rows, but not raw request counts or failure-rate fields. Exact public
  completion/failure-rate comparison is therefore not available from the public
  dashboard export.
- Worker-step `FAILED 3:0` and `CANCELLED 0:9` states observed in `sacct` are
  teardown noise after successful benchmark completion; each parent job wrote
  rollup artifacts and exited `0:0`.
