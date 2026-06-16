# vLLM Sidecar Request Migration and Cancellation FT

Run date: 2026-06-15 PDT / 2026-06-16 UTC

## Summary

The vLLM sidecar should not stay healthy after its paired vLLM OpenEngine server dies. A healthy sidecar without a healthy engine can only advertise a dead worker and poison routing. The patch under test makes engine liveness a first-class backend lifecycle signal:

- `LLMEngine::watch()` can now request worker shutdown.
- The worker races the serving future, shutdown token, and engine watcher.
- The vLLM sidecar turns fatal OpenEngine `Generate` failures, premature stream closes, and failed `Health` checks into `BackendEngineShutdown`.
- On engine death, the sidecar runs normal graceful orchestration: unregister from discovery, drain/cleanup, then return the engine shutdown error so the sidecar process exits non-zero.
- The frontend sees the typed engine-shutdown error as migratable and recreates the stream on a remaining worker when migration is enabled.

Result: full cancellation/migration matrix passed, including engine-only failure on both TCP and NATS request planes.

## Environment

| Item | Value |
|---|---|
| Cluster allocation | dlcluster job `1310086` |
| Node | `4u4g-0097` |
| GPUs | 2x NVIDIA A100 80GB PCIe |
| Container image under test | `sidecar-ft-dev:liveness` (`8e265d874c85`, 28.9 GB) |
| Model | `Qwen/Qwen3-0.6B` |
| Dynamo fork | `feat/vllm-sidecar-openengine` at `386ab427b8212fabb4f5ba477b2feede0cb9ca6b` plus local liveness patch |
| vLLM fork | `feat/openengine-grpc-server` at `ecf9f078f81749732e5f13a5507347cb4d6f0674` |
| Local artifacts | `/home/connorc/sidecar/sidecar-ft-artifacts-1310086-attempt4` |
| Remote artifacts | `/tmp/sidecar-ft-liveness/sidecar-ft-runs-full-after-liveness-patch-20260615-4` |

The final matrix was launched with:

```bash
python /workspace/sidecar_ft_runner.py \
  --root /workspace/sidecar-ft-runs-full-after-liveness-patch-20260615-4 \
  --summary /workspace/sidecar-ft-runs-full-after-liveness-patch-20260615-4/summary.json \
  --planes tcp,nats \
  --scenarios baseline,cancellation,migration_group,migration_sidecar,migration_engine,migration_disabled,migration_max_seq_len
```

Pre-FT verification also passed in the same container image:

- `cargo fmt --check`
- `cargo test -p dynamo-vllm-sidecar` (`30 passed`)
- `python3 -m py_compile /home/connorc/sidecar/sidecar_ft_runner.py`
- `git -C /home/connorc/sidecar/dynamo diff --check`

## Results

Final matrix exit: `0`.

| Plane | Scenario | Status | Key checks |
|---|---:|---:|---|
| TCP | `baseline` | pass | Owner `2`, streamed `130` chunks |
| TCP | `cancellation` | pass | Frontend cancellations `1`, worker cancellations `1` |
| TCP | `migration_group` | pass | Owner `1` killed, backup `2`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| TCP | `migration_sidecar` | pass | Owner `1` sidecar killed, backup `2`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| TCP | `migration_engine` | pass | Owner `2` engine killed, backup `1`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| TCP | `migration_disabled` | pass | Request failed as expected, `success=false`, `backup_replayed=false` |
| TCP | `migration_max_seq_len` | pass | Request failed as expected, `success=false`, `backup_replayed=false`, `max_seq_len_exceeded=1` |
| NATS | `baseline` | pass | Owner `2`, streamed `130` chunks |
| NATS | `cancellation` | pass | Frontend cancellations `1`, worker cancellations `1` |
| NATS | `migration_group` | pass | Owner `1` killed, backup `2`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| NATS | `migration_sidecar` | pass | Owner `1` sidecar killed, backup `2`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| NATS | `migration_engine` | pass | Owner `1` engine killed, backup `2`, `success=true`, `backup_replayed=true`, `ongoing_migrations=1` |
| NATS | `migration_disabled` | pass | Request failed as expected, `success=false`, `backup_replayed=false` |
| NATS | `migration_max_seq_len` | pass | Request failed as expected, `success=false`, `backup_replayed=false`, `max_seq_len_exceeded=1` |

Note: the negative-control rows can still show `ongoing_migrations=1` and `recreated_log=true` in the raw summary because the frontend enters the migration path before the scenario rejects completion. The pass condition for those controls is no successful response and no backup replay.

## Engine-Death Evidence

TCP engine-only failure (`tcp-migration_engine-1781569772`):

- Killed worker: sidecar `2`, instance `949026753376925711`.
- `sidecar2.log` reports `Engine liveness watcher failed; running graceful orchestration` with `BackendEngineShutdown: OpenEngine Generate RPC failed`.
- `sidecar2.log` then shows discovery unregister and `Engine cleanup complete`.
- `sidecar2.log` exits with `Error: BackendEngineShutdown: OpenEngine Generate RPC failed`.
- `frontend.log` reports the instance down due to the migratable `BackendEngineShutdown` and then logs `Stream disconnected, recreating stream`.
- Summary shows backup `1`, `backup_replayed=true`, `success=true`, `ongoing_migrations=1`.

NATS engine-only failure (`nats-migration_engine-1781570274`):

- Killed worker: sidecar `1`, instance `3513545266316254215`.
- `sidecar1.log` reports `Engine liveness watcher failed; running graceful orchestration` with `BackendEngineShutdown: OpenEngine Generate RPC failed`.
- `sidecar1.log` then shows discovery unregister and `Engine cleanup complete`.
- `sidecar1.log` exits with `Error: BackendEngineShutdown: OpenEngine Generate RPC failed`.
- `frontend.log` reports the instance down due to the migratable `BackendEngineShutdown` and then logs `Stream disconnected, recreating stream`.
- Summary shows backup `2`, `backup_replayed=true`, `success=true`, `ongoing_migrations=1`.

## Harness Notes

Earlier runs exposed harness issues rather than product failures:

- Attempt 1 and attempt 2 reused fixed OpenEngine ports and eventually failed startup with `address already in use`.
- Attempt 3 used dynamic ports but generated `DYN_SYSTEM_PORT` values above the sidecar's `i16` parser limit.
- Attempt 4 used per-scenario low port blocks and is the clean run reported above.

The copied local artifacts exclude the root-owned `etcd-data` directories. All scenario logs, top-level summary, frontend logs, sidecar logs, engine logs, NATS logs, and etcd process logs were copied.
