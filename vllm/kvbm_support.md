# KVBM support in the vLLM sidecar

Status of **KVBM** (the Dynamo KV Block Manager — multi-tier KV cache offloading
across G1 GPU / G2 CPU-pinned / G3 NVMe / G4 remote) through the vLLM **sidecar**
(Dynamo over OpenEngine), plus the configuration the sidecar topology requires.

Unlike audio/video multimodal (see [`multimodal_support.md`](./multimodal_support.md)),
KVBM reaches **full parity** through the sidecar for tiering, KV-aware routing,
and prefill/decode disaggregation. The reason is structural: KVBM lives entirely
*inside* the engine process the sidecar already drives.

Companion to [`implementation_brief.md`](./implementation_brief.md) and
[`openengine_api.md`](./openengine_api.md) (the `GetKvEventSources` /
`KvSessionRef` wire contract KVBM rides on).

---

## TL;DR

| Capability | Sidecar status | Notes |
|---|---|---|
| **Aggregated tiering** (G1→G2→G3 offload) | ✅ validated e2e | KVBM runs in the engine; sidecar unchanged |
| **KV-aware routing** w/ consolidated multi-tier events | ✅ validated e2e | needed the consolidator empty-topic fix (below) |
| **Disaggregated** P/D (PdConnector = KVBM + NIXL) | ✅ validated e2e | needs `--disable-hybrid-kv-cache-manager` (below) |
| **Remote G4 / S3** + DRT-coupled cross-instance | ⏸️ deferred | needs a DistributedRuntime in the standalone engine |

All of the above was validated end-to-end on an H100 (LLaVA-class small model
`Qwen/Qwen3-0.6B`), built entirely from the forks. The only open item is the
deferred Phase D.

---

## Architecture: why KVBM "just rides along"

The sidecar deployment runs four cooperating processes:

```
Dynamo frontend ──HTTP/OpenAI──► Dynamo sidecar worker (dynamo-vllm-sidecar)
                                          │  OpenEngine v1 gRPC
                                          ▼
                                 vllm-rs serve  ── the Rust "P0" frontend
                                          │  engine-core ZMQ (msgpack)
                                          ▼
                                 headless Python EngineCore ("P1")  ◄── KVBM lives here
                                 (scheduler + model executor on the GPU)
```

**KVBM is a vLLM KV connector (`DynamoConnector`), and both of its halves run
inside the engine process:** the connector **leader** runs in the headless
EngineCore scheduler, and the connector **worker** runs in the GPU worker. The
Dynamo sidecar (`dynamo-vllm-sidecar`) imports no torch/CUDA/NIXL and never
imports `kvbm`; it is just an OpenEngine client.

So the contrast with the audio/video gap is exact: multimodal *preprocessing*
was missing from the engine path, but KVBM's *data plane* (offload/onboard
between tiers, NIXL transfers, the consolidator) is already in the engine. The
sidecar's job is only to:

- **relay the opaque P/D handoff** (`KvSessionRef` ⇄ `kv_transfer_params`) for
  disaggregation — KVBM's NIXL transfer is engine-internal; and
- **advertise the engine's KV-event source** (`GetKvEventSources`) so the
  Dynamo KV router can index KVBM's multi-tier events for routing.

That means KVBM is turned on exactly as in the in-process path — via
`--kv-transfer-config` and `DYN_KVBM_*` env — **attached to `vllm-rs serve`**
(which inherits them down to the EngineCore), **not** to the Dynamo sidecar.

---

## What works

### 1. Aggregated tiering (G1→G2→G3)

Launch `vllm-rs serve` with the KVBM connector; the offload engine runs in the
EngineCore and tiers KV blocks GPU→host→disk. Validated by KVBM's own Prometheus
metrics on the engine (`kvbm_offload_blocks_d2h` incrementing on prefix reuse).
The sidecar needs no code changes — it discovers the (KVBM-extended) cache size
from the engine handshake like any other capacity field.
Launch: `sidecar_agg_kvbm.sh`.

### 2. KV-aware routing with consolidated multi-tier events

KVBM emits store/remove events tagged with a `StorageMedium` (GPU/CPU/disk). A
**KV Event Consolidator** (started by the connector leader inside the engine)
subscribes to vLLM's raw ZMQ KV-event publisher, dedups/merges the multi-tier
events, and republishes one coherent stream. The flow through the sidecar:

```
vLLM ZMQ KV events ─► KVBM consolidator (in engine) ─► engine handshake advertises
                                                        the consolidator endpoint
   ─► sidecar GetKvEventSources surfaces it ─► Dynamo KV router subscribes + indexes
```

Validated e2e: on a shared 72-block prefix the router reports `overlap_blocks=71/72`
(was `0/72` before the empty-topic fix), and with **two** engines the router
scores both workers per request and routes to the prefix-holding one
(`0/54` cold → `53/54` warm). Launch: `sidecar_agg_kvbm_router.sh`.

### 3. Disaggregated P/D (PdConnector = KVBM + NIXL)

The prefill engine runs a `PdConnector` chaining `DynamoConnector` (KVBM tiering)
with `NixlConnector` (the P/D transfer); the decode engine runs a plain
`NixlConnector`. The sidecar derives roles from the engine's `kv_role`
(`kv_producer`→prefill, `kv_consumer`→decode) and relays the opaque
`kv_transfer_params` as a `KvSessionRef`. KVBM tiers on prefill; the
prefill→decode KV handoff moves over NIXL engine-internally (no new sidecar
transfer code). Validated e2e: NIXL handshake passes, the handoff completes,
and KVBM offload is active on prefill. Launch: `sidecar_disagg_kvbm.sh`.

---

## Required configuration & gotchas (found during e2e validation)

These are the non-obvious bits the sidecar/headless topology requires that the
in-process path doesn't make you think about.

- **KVBM config goes on the engine, not the sidecar.** `--kv-transfer-config`
  (`DynamoConnector`/`PdConnector`) and `DYN_KVBM_*` env attach to `vllm-rs serve`
  and are inherited by the headless EngineCore. The Dynamo sidecar worker never
  sees them.

- **Run single-node: `DYN_RUNTIME_ENABLED_KVBM=0`.** Tiering (G1→G2→G3) needs no
  Dynamo DistributedRuntime. Setting it to `1` makes the connector call
  `DistributedRuntime.detached()` inside the standalone headless engine, which
  can crash the process uncatchably — this is exactly why remote/cross-instance
  KVBM (Phase D) is deferred.

- **The consolidator publishes on an EMPTY ZMQ topic.** The raw vLLM publisher
  tags events with topic `kv-events`, but the consolidator republishes with an
  empty topic. The OpenEngine source advertised by `GetKvEventSources` must
  therefore declare an **empty** topic for the consolidator endpoint — a
  `kv-events` SUB filter does prefix-matching and silently drops every
  empty-topic message, leaving the router index empty (KV routing silently
  non-operational). Fixed in `build_kv_event_sources`.

- **Disaggregation requires `--disable-hybrid-kv-cache-manager` on BOTH
  engines.** The `PdConnector`/`MultiConnector` asserts the hybrid KV-cache
  manager (HMA) is off unless every sub-connector supports it (KVBM does not),
  and the auto-disable that fires for a *single* connector does **not** fire
  through `MultiConnector` — so the prefill engine hits a startup
  `AssertionError` without the flag. The decode engine needs the same flag so
  its KV-cache layout matches prefill's; otherwise the NIXL prefill→decode
  handshake fails its compatibility-hash check.

- **Request plane / KV-event ports** are per-engine. When co-locating engines
  (e.g. P/D on one GPU, or two routed engines), give each distinct
  `--openengine-port`, `--kv-events-config` endpoint, `DYN_KVBM_LEADER_ZMQ_PUB_PORT`,
  and `VLLM_NIXL_SIDE_CHANNEL_PORT`.

---

## Deferred — remote G4 / DRT-coupled (Phase D)

Remote/S3 (G4) offload and cross-instance KVBM block sharing both need a Dynamo
`DistributedRuntime` *inside* the standalone headless engine. Today
`DYN_RUNTIME_ENABLED_KVBM=1` → `DistributedRuntime.detached()` in that process
can crash uncatchably, so this is a separate, larger effort and intentionally
out of scope for the current sidecar KVBM support.

---

## Pointers

| Area | Location |
|---|---|
| KVBM connector (engine-side, reused as-is) | `dynamo/lib/bindings/kvbm/python/kvbm/vllm_integration/connector/` |
| Consolidator endpoint derivation | `dynamo/lib/bindings/kvbm/python/kvbm/vllm_integration/consolidator_config.py` |
| Consolidator endpoint injection (headless engine) | `vllm/vllm/entrypoints/cli/serve.py` (`run_headless`) |
| Engine handshake field `kv_events_consolidated_endpoint` | `vllm/vllm/v1/engine/{__init__.py,core.py}` + `vllm/rust/src/engine-core-client/src/protocol/handshake.rs` |
| Sidecar KV-event source advertising (empty-topic fix) | `vllm/rust/src/server/src/grpc/openengine/mod.rs` (`build_kv_event_sources`) |
| Sidecar KV-event consumption + P/D relay | `dynamo/lib/vllm-sidecar/src/engine.rs` (`kv_event_sources`, kv_session round-trip) |
| Launch scripts | `dynamo/examples/backends/vllm/launch/sidecar_agg_kvbm.sh`, `sidecar_agg_kvbm_router.sh`, `sidecar_disagg_kvbm.sh` |
| In-process counterparts (parity reference) | `dynamo/examples/backends/vllm/launch/agg_kvbm.sh`, `agg_kvbm_router.sh`, `disagg_kvbm.sh` |
