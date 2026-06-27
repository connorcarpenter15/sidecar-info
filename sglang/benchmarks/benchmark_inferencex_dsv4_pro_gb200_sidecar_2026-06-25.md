# InferenceX DSV4 Pro GB200 SGLang Sidecar Benchmark

> **Superseded attempt.** This document records the failed `20260518` image
> smoke. The full eight-row matrix subsequently completed with the `20260615`
> image. See the [final findings](benchmark_inferencex_dsv4_pro_gb200_sidecar_findings_2026-06-26.md)
> and [detailed run report](../../benchmarks/sglang/benchmark_inferencex_dsv4_pro_gb200_sidecar_2026-06-25.md).

**Status:** smoke gate failed on Lyris job `2214437`; the seven larger rows
were not submitted.

This run is diagnostic-only because the exact public InferenceX container
`lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85` was not available. The
closest working SGLang container found on Lyris was:

`/lustre/fsw/coreai_dlfw_dev/shuw/dsv4/srt-slurm/lmsysorg+sglang+nightly-dev-cu13-20260518-c67b2870.sqsh`

It is 10 days before the public image tag and passed a CUDA probe inside Pyxis:
`torch.cuda.is_available() == True`, `torch.cuda.device_count() == 4`.

## Locked Public Target

- Model: `deepseek-ai/DeepSeek-V4-Pro`
- Model revision used from Lyris cache:
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

## Implemented Recipes

Local diagnostic recipe directory:

`/home/connorc/sidecar/srt-slurm-sidecar/recipes/sglang/deepseek-v4-pro-sa-gb200-8k1k-sidecar-diagnostic-20260518/`

All eight non-MTP recipes exist, and no `*mtp*.yaml` files are present.

| Recipe | Public topology | Status |
|---|---|---|
| `disagg-gb200-1p1d-tp8-tp8-4-c1.yaml` | 1P x 8 GPUs, 1D x 8 GPUs, C=1 | `failed-public-topology`, diagnostic container, job `2214437` |
| `disagg-gb200-1p4d-dep8-tp8-10-c64.yaml` | 1P x 8 GPUs, 4D x 8 GPUs, C=64 | not submitted, smoke gate failed |
| `disagg-gb200-1p2d-dep8-dep16-10-c256.yaml` | 1P x 8 GPUs, 2D x 16 GPUs, C=256 | not submitted, smoke gate failed |
| `disagg-gb200-1p1d-dep8-dep16-6-c512.yaml` | 1P x 8 GPUs, 1D x 16 GPUs, C=512 | not submitted, smoke gate failed |
| `disagg-gb200-2p1d-dep8-dep16-8-c1536.yaml` | 2P x 8 GPUs, 1D x 16 GPUs, C=1536 | not submitted, smoke gate failed |
| `disagg-gb200-4p1d-dep8-dep16-12-c4096.yaml` | 4P x 8 GPUs, 1D x 16 GPUs, C=4096 | not submitted, smoke gate failed |
| `disagg-gb200-5p1d-dep8-dep16-14-c8192.yaml` | 5P x 8 GPUs, 1D x 16 GPUs, C=8192 | not submitted, smoke gate failed |
| `disagg-gb200-6p1d-dep8-dep12-15-c8192.yaml` | 6P x 8 GPUs, 1D x 12 GPUs, C=8192 | not submitted, smoke gate failed |

Recipe-wide sidecar-only deltas:

- `setup_script: sglang-sidecar-deps.sh`
- `backend.openengine_sidecar: true`
- `backend.sidecar_binary: "dynamo-sglang-sidecar"`
- `SGLANG_OPENENGINE_RESPONSE_TIMEOUT_SECS: "100000"`
- Sidecar artifact mount:
  `/lustre/fsw/coreai_dlfw_dev/connorc/sidecar-artifacts:/sidecar-artifacts`
- Identity block added to all recipes.

Benchmark-client compatibility delta:

- `benchmark.custom_tokenizer:
  "sa_bench_tokenizers.sglang_deepseek_v4.SGLangDeepseekV4Tokenizer"`
- Reason: the selected `20260518` runtime cannot load DSV4 through default
  Transformers `AutoTokenizer` in SA-Bench. Lyris `srtctl` supports
  `custom_tokenizer` but not the newer `tokenizer_mode: deepseek_v4` field.

## Container Selection

Confirmed unavailable:

- `lmsysorg/sglang:nightly-dev-cu13-20260528-0abe6a85`

Rejected after probe:

- `docker.io/lmsysorg/sglang:nightly-dev-cu13-20260611-99ab90c5`
- Imported SquashFS:
  `/lustre/fsw/coreai_dlfw_dev/connorc/containers/sglang-nightly-dev-cu13-20260611-99ab90c5.sqsh`
- SHA256:
  `c6e494b08a2b7cfc779dcb73b4180cbc4f2e7af8466cc3eee59bfe9080e8fab4`
- Probe result inside Pyxis:
  `torch.__version__ == 2.11.0+cu130`, `torch.version.cuda == 13.0`,
  `torch.cuda.is_available() == False`, `torch.cuda.device_count() == 0`

Selected closest working image:

- `docker.io/lmsysorg/sglang:nightly-dev-cu13-20260518-c67b2870`
- Lyris SquashFS:
  `/lustre/fsw/coreai_dlfw_dev/shuw/dsv4/srt-slurm/lmsysorg+sglang+nightly-dev-cu13-20260518-c67b2870.sqsh`
- Probe result inside Pyxis:
  `torch.__version__ == 2.11.0+cu130`, `torch.version.cuda == 13.0`,
  `torch.cuda.is_available() == True`, `torch.cuda.device_count() == 4`

## Sidecar Artifacts

Artifact staging directory:

`/lustre/fsw/coreai_dlfw_dev/connorc/sidecar-artifacts/`

| Artifact | State | SHA256 |
|---|---|---|
| `dynamo-sglang-sidecar` | ARM aarch64 executable | `a398adc40a1187b30f3469147eddb109ce35600db8589fd0a4597a8f8a3ac101` |
| `lib_core.so` | ARM aarch64 shared object | `19528a808e45f47e4b08b909cc5602c3946259659c5914b617122ef3a75ce0db` |
| `openengine_server.py` | Python overlay | `fc45e9cd3b7f7e8ba45d30d4538389da1cda770d892ce7d904736fe9cc20bb3f` |

Effective setup script location on Lyris:

`/lustre/fsw/coreai_dlfw_dev/connorc/.local/bin-aarch64/sglang-sidecar-deps.sh`

The setup script stages the sidecar binary, replaces Triton bundled `ptxas`,
and overlays SGLang `_core` plus `openengine_server.py`.

## Run Log

| Job | Image | Classification | Outcome |
|---|---|---|---|
| `2214180` | initial sidecar recipe | diagnostic-only | failed: `/sidecar-artifacts` was not mounted |
| `2214226` | `20260611` | diagnostic-only | cancelled: effective `/configs` mount lacked setup script |
| `2214233` | `20260611` | diagnostic-only | failed: setup succeeded, SGLang saw no accelerator |
| `2214304` | `20260611` | diagnostic-only | failed: `torch.cuda` unavailable in container |
| `2214347` | `20260518` | diagnostic-only, exact public topology | server healthy and endpoint verification passed; SA-Bench failed to load default DSV4 tokenizer |
| `2214437` | `20260518` | diagnostic-only, failed public topology | server healthy, identity verified, custom tokenizer loaded; decode worker crashed during smoke benchmark |

Final smoke details:

- Job ID: `2214437`
- Output directory:
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2214437`
- Nodes: `lyris0048`, `lyris0049`, `lyris0050`, `lyris0051`
- SLURM state: `FAILED`, exit `1:0`, elapsed `00:14:03`
- Server health: passed at `2026-06-25 21:42:45 PDT`
- Identity verification: model revision, Dynamo `1.2.0`, and SGLang
  `0.0.0.dev1+g2a357071e` verified
- SA-Bench command included:
  `sa_bench_tokenizers.sglang_deepseek_v4.SGLangDeepseekV4Tokenizer`
- Endpoint verification returned a completion before benchmark traffic.
- No `results*.json` was produced under
  `/lustre/fsw/coreai_dlfw_dev/connorc/srt-slurm/outputs/2214437/logs/sa-bench_isl_8192_osl_1024`

Failure evidence:

- `benchmark.out` initial test run completed but all requests failed.
- Main benchmark step started, then was cancelled at `2026-06-25 21:43:27 PDT`.
- Decode logs show `torch.AcceleratorError: CUDA error: an illegal memory access was encountered` in
  `/sgl-workspace/sglang/python/sglang/srt/managers/scheduler_output_processor_mixin.py`
  during `result.copy_done.synchronize()`.
- Orchestrator reported critical process `decode_0_lyris0051` exited with
  code `137` and cleaned up the job.

## Acceptance Gate

The full seven remaining rows were not submitted because smoke `2214437` did
not complete result collection. Any future row using the `20260518` image must
remain `diagnostic-only`; only the unavailable `20260528-0abe6a85` image can be
an exact public container match.
