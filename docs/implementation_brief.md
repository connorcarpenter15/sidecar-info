# Dynamo Sidecar / Remote Backend Implementation Brief

## Purpose

This brief defines the Dynamo sidecar architecture and ownership boundaries.

## Local diagram references

The diagrams are intentionally stored outside this document. Use the `.mmd`
files as editable sources and the `.png` files as rendered references.

| Flow | Source | Rendered |
|---|---|---|
| Aggregated request | [`agg_request.mmd`](./diagrams/agg_request.mmd) | [`agg_request.png`](./diagrams/assets/agg_request.png) |
| vLLM disaggregation | [`disagg_request_vllm.mmd`](./vllm/disagg_request_vllm.mmd) | [`disagg_request_vllm.png`](./vllm/assets/disagg_request_vllm.png) |
| Cancellation | [`request_cancellation.mmd`](./diagrams/request_cancellation.mmd) | [`request_cancellation.png`](./diagrams/assets/request_cancellation.png) |
| Migration | [`request_migration.mmd`](./diagrams/request_migration.mmd) | [`request_migration.png`](./diagrams/assets/request_migration.png) |
| OpenEngine API | [`openengine_api.md`](./openengine_api.md) | N/A |

## Why this approach exists

The sidecar keeps engine execution out of the Dynamo process:

- Native engine UX stays familiar.
- Engine and Dynamo dependencies stay isolated.
- Dynamo owns orchestration, routing, KV indexing, event normalization, request
  migration, and control-plane integration.
- Engines own their native serving stack, scheduler, token generation,
  engine-local KV transfer mechanics, and engine-specific runtime behavior.

See [Why OpenEngine](https://github.com/connorcarpenter15/openengine/blob/main/docs/motivation.md)
for the protocol rationale and [SGLang sidecar adoption](sglang/openengine_adoption.md)
for an engine-specific example.

## Product boundary

The sidecar approach changes Dynamo from direct runtime/request ownership
toward event-driven orchestration over engine services.

### Dynamo should own

- Frontend API handling.
- Client request normalization into Dynamo request state.
- KV-aware routing and worker selection.
- Request-plane communication from frontend to sidecars.
- Event-plane ingestion from sidecars.
- Dynamo routing state: worker capacity, request status, KV metadata, and KV
  index.
- Request migration based on accumulated streamed output state.
- Cross-engine normalization and compatibility testing.
- OpenEngine client implementation inside the sidecar.
- Policy decisions: retry, cancellation propagation, drain, health
  interpretation, admission, routing, and scaling signals.

### Engine runtimes should own

- Native engine process startup and lifecycle.
- Native API surface and engine flags.
- Engine-local preprocessing/postprocessing where possible.
- Native scheduler and generation behavior.
- Engine-native KV allocation and transfer mechanics.
- Native engine health and load reporting, exposed through OpenEngine.
- KV event emission, exposed through OpenEngine streams or through advertised
  compatibility sources.

### Sidecar should own

The sidecar is the adapter between Dynamo and the native engine runtime. It
should:

- Receive Dynamo internal requests from the frontend.
- Normalize Dynamo request state into OpenEngine request schema.
- Call the engine through OpenEngine API.
- Normalize OpenEngine responses back into Dynamo response schema.
- Subscribe to or discover engine events.
- Normalize OpenEngine event state into Dynamo routing state.
- Publish Dynamo routing/state events to the frontend/KV router.
- Translate stable engine errors into Dynamo errors.
- Hide per-engine differences from the Dynamo frontend as much as possible.

## Core architecture

The normal request path should be:

```text
Client
  -> Dynamo Frontend + KV Router
      -> Dynamo Sidecar
          -> Native Engine Server
```

For the standard deployment, the KV router is embedded in the Dynamo frontend
process. Sidecars and engine servers are separate processes. A sidecar may run
in the same pod or host as the engine, but the implementation should avoid
relying on same-process assumptions.

## OpenEngine API contract expectations

OpenEngine is the engine-facing contract between the Dynamo sidecar and the
native engine server. The sidecar should use OpenEngine for both
request/response traffic and the event contract Dynamo needs for routing and
control-plane state.

The minimal contract should cover:

- Generation: `Generate(GenerateRequest) -> stream GenerateResponse`.
- Engine metadata: `GetEngineInfo`, including engine name, version, API
  version, role, instance ID, supported models, parallelism, and KV connector
  info.
- Model metadata: `GetModelInfo`, including max context length, max output
  tokens, KV block size, capacity limits, tokenizer modes, and feature support.
- Load metadata: `GetLoad`.
- Health and lifecycle: `Health`, `Abort`, `Drain`.
- Disaggregated serving / KV transfer: `GetKvConnectorInfo`,
  `GetKvEventSources`, `SubscribeKvEvents`.
- Runtime events: `SubscribeRuntimeEvents`.

OpenEngine should model engine roles explicitly:

- `AGGREGATED`: accepts normal generation requests and returns tokens.
- `PREFILL`: accepts prefill requests, builds KV state, emits handoff/session
  readiness, and does not perform normal decode generation.
- `DECODE`: accepts decode requests with KV session/handoff metadata and
  returns generated tokens.

The sidecar should enforce role/request compatibility before forwarding to the
engine where possible. Engines must also validate role/request compatibility
and return stable errors.

## Request and response schemas

The agent should keep the request translation layers simple and explicit:

1. Client request → Dynamo request schema.
2. Dynamo request schema → OpenEngine request schema.
3. OpenEngine request schema → engine-native request schema.
4. Engine-native response → OpenEngine response schema.
5. OpenEngine response schema → Dynamo response schema.
6. Dynamo response schema → client stream.

Avoid leaking engine-native fields into the Dynamo frontend except through
intentional Dynamo metadata fields. Engine-specific behavior should be isolated
in the sidecar or in engine-owned OpenEngine adapters.

## Normal aggregated request

Reference diagrams:

- Editable source: [`agg_request.mmd`](./diagrams/agg_request.mmd)
- Rendered asset: [`assets/agg_request.png`](./diagrams/assets/agg_request.png)

Expected implementation shape:

1. Client sends a request to Dynamo frontend.
2. Frontend authenticates/authorizes and normalizes to Dynamo request schema.
3. Embedded KV router selects an aggregated worker.
4. Frontend forwards the Dynamo request to the selected sidecar.
5. Sidecar normalizes to OpenEngine request schema.
6. Sidecar invokes the engine over OpenEngine API.
7. Engine normalizes to engine-native schema and executes prefill + decode in
   the same engine runtime.
8. Engine streams tokens, usage, finish reason, and errors over OpenEngine API.
9. Sidecar normalizes to Dynamo response schema.
10. Frontend streams response to the client.
11. In parallel, the engine emits OpenEngine events for request status, KV
    events, metrics, and health/load state.
12. Sidecar normalizes those events into Dynamo routing state and publishes
    them to the frontend/KV router.

Implementation notes:

- Keep the frontend unaware of engine-native request/response formats.
- Keep KV router state updates in the frontend process for the normal
  deployment.
- Make event ingestion explicit. Do not treat events as optional if the routing
  policy depends on them.
- If the engine cannot emit native OpenEngine events yet, sidecar should use
  compatibility discovery where available and clearly mark reduced fidelity.

## Disaggregated request with vLLM

Reference diagrams:

- Editable source: [`disagg_request_vllm.mmd`](./vllm/disagg_request_vllm.mmd)
- Rendered asset:
  [`assets/disagg_request_vllm.png`](./vllm/assets/disagg_request_vllm.png)

Expected implementation shape:

1. Frontend normalizes the request and selects a prefill worker using the KV
   router.
2. Frontend forwards a Dynamo prefill request to the prefill sidecar.
3. Prefill sidecar normalizes to OpenEngine prefill request schema.
4. Prefill sidecar invokes vLLM prefill over OpenEngine API.
5. vLLM prefill normalizes to engine-native request schema and executes prompt
   processing / KV population.
6. Prefill returns KV handoff metadata through OpenEngine.
7. Prefill sidecar normalizes the result to Dynamo prefill response schema.
8. Frontend updates routing state and selects a decode worker.
9. Frontend forwards a Dynamo decode request with KV handoff metadata to the
   decode sidecar.
10. Decode sidecar normalizes to OpenEngine decode request schema.
11. Decode sidecar invokes vLLM decode over OpenEngine API.
12. vLLM decode attaches the KV transfer/session metadata and generates tokens.
13. Decode streams tokens over OpenEngine API.
14. Decode sidecar normalizes to Dynamo response schema and streams back
    through the frontend to the client.

vLLM-specific notes:

- Today, vLLM disagg requires Dynamo-side adaptation around prefill and decode
  roles.
- The existing wrapper path has logic that makes prefill generate a small
  controlled result to obtain KV transfer params.
- The sidecar/OpenEngine design should move toward an explicit `PrefillReady` /
  `KvSessionRef`-style contract instead of relying on wrapper-specific
  conventions.
- vLLM-native KV events and NIXL transfer mechanisms should remain engine-owned
  and exposed through OpenEngine or compatibility discovery.
- Watch multimodal edge cases carefully. Some models require embedding metadata
  or expanded prompt token IDs to be passed from prefill to decode.

## Request cancellation

Reference diagrams:

- Editable source: [`request_cancellation.mmd`](./diagrams/request_cancellation.mmd)
- Rendered asset:
  [`assets/request_cancellation.png`](./diagrams/assets/request_cancellation.png)

Expected implementation shape:

1. Request is already running through frontend → sidecar → engine.
2. Client disconnects or explicitly cancels.
3. Frontend marks the request as cancelled.
4. Frontend sends Dynamo cancellation to the sidecar.
5. Sidecar normalizes to OpenEngine cancellation schema.
6. Sidecar calls OpenEngine `Abort` or equivalent cancellation flow.
7. Engine normalizes to engine-native cancellation and stops
   scheduling/generation.
8. Engine releases request resources.
9. Engine acknowledges cancellation through OpenEngine.
10. Sidecar normalizes cancellation result to Dynamo.
11. Frontend finalizes cancelled request state and stops the client stream.
12. Event plane publishes cancellation, capacity release, KV cleanup, and
    request status updates.

Cancellation implementation notes:

- Cancellation must be idempotent.
- Cancellation must tolerate races with normal request completion.
- Cancellation must release worker capacity even if the engine does not return
  a clean final response.
- For disaggregated paths, cancellation may need to reach both prefill and
  decode roles.
- Avoid assuming cancellation is safe during all KV transfer phases;
  engine-specific behavior may require guards.

## Request migration

Reference diagrams:

- Editable source: [`request_migration.mmd`](./diagrams/request_migration.mmd)
- Rendered asset:
  [`assets/request_migration.png`](./diagrams/assets/request_migration.png)

Important: OpenEngine v1 should **not** require a request migration API.

Current Dynamo request migration is handled on the Dynamo side by accumulating
streamed output state. If a request or engine fails, Dynamo rebuilds the
request from the prompt plus already received output tokens and sends that
rebuilt request to another worker. The sidecar architecture should preserve
this behavior rather than requiring engines to export and restore opaque
migration state.

Expected implementation shape:

1. Initial request flow is already established.
2. Frontend is accumulating generated tokens as they are streamed back.
3. Source engine or source stream fails.
4. Source sidecar propagates stream failure to frontend.
5. Frontend detects whether the failure is migratable.
6. Frontend rebuilds the Dynamo request from accumulated state: prompt tokens,
   received output tokens, sampling params, stop conditions, and updated token
   budget.
7. Frontend selects a target worker using the KV router.
8. Frontend forwards the rebuilt request to the target sidecar.
9. Target sidecar normalizes to OpenEngine request schema and invokes the
   target engine.
10. Target engine continues generation using accumulated tokens as context.
11. Target sidecar normalizes the response back to Dynamo response schema.
12. Frontend continues streaming to the client.
13. Event plane updates source failure, target ownership, worker capacity,
    request status, and KV/router state.

Migration implementation notes:

- Do not add `ExportRequestState`, `ImportRequestState`, or similar migration
  APIs to OpenEngine v1.
- Migration should be transparent to the client.
- Avoid token duplication or token loss.
- Keep remaining token budget accurate.
- Preserve stop conditions and sampling params.
- Disable or fail fast for unsupported cases such as multi-choice or guided
  decoding unless state replay semantics are proven correct.
- Ensure migration counters and failure reasons are observable at the frontend.

## Event model

The event contract is the real API surface of the sidecar approach. It must be
treated as a versioned compatibility contract, not as incidental telemetry.

Required event categories:

- Request status: accepted, running, first token, completed, failed, cancelled.
- KV events: block stored, block removed, all blocks cleared, session/handoff
  metadata.
- Capacity/load events: running requests, queued requests, available KV
  capacity, scheduling load.
- Health events: ready, degraded, draining, unhealthy.
- Metrics events: request/iteration metrics needed by router, planner, and
  autoscaling.
- Error events: stable error classes and retryability/migratability hints.

OpenEngine should support two KV-event modes:

1. Native OpenEngine stream via `SubscribeKvEvents`.
2. Compatibility discovery via `GetKvEventSources`, allowing engines to
   advertise existing ZMQ or engine-native publishers during migration.

Sidecar responsibilities for events:

- Subscribe to OpenEngine events or discover compatible engine-native event
  sources.
- Normalize event payloads to Dynamo routing state.
- Maintain monotonic ordering and sequence metadata when available.
- Preserve data-parallel rank attribution.
- Publish normalized state to the frontend/KV router.
- Detect missing, delayed, duplicated, or out-of-order events where possible.

## Process and deployment boundaries

The remote backend path should support these process boundaries:

```text
Dynamo Frontend + KV Router process Dynamo Sidecar process Native
Engine Server process External discovery/event infrastructure as needed
```

Deployment expectations:

- The sidecar may run in the same pod/host as the engine, but should still
  communicate through OpenEngine rather than private in-process APIs.
- The engine should be launchable through native entrypoints.
- Dynamo-specific configuration should stay primarily on Dynamo components.
- Engine-owned flags should remain native engine flags.
- The sidecar should be replaceable or upgradable without rebuilding the engine
  container where possible.

## Test matrix

### Functional tests

- Aggregated text generation.
- Aggregated streaming generation.
- Aggregated cancellation.
- Aggregated request failure and error mapping.
- vLLM disaggregated prefill/decode.
- KV event ingestion.
- Load/health event ingestion.
- Request migration by stream failure.
- Drain and shutdown behavior.

### Compatibility tests

- Multiple vLLM versions.
- Engines with native OpenEngine KV stream.
- Engines with only compatibility event sources.
- Engines with missing optional capabilities.
- Role/request mismatch errors.
- Schema version mismatch errors.

### Performance tests

- Sidecar overhead for normal aggregated request.
- OpenEngine serialization overhead.
- Event emission overhead.
- Tokenization/KV matching overhead if performed outside the engine.
- Local RPC versus remote RPC overhead.
- Streaming latency and first-token latency.
- Disaggregated prefill/decode throughput.
- Router scheduling overhead under high concurrency.

### Failure tests

- Engine dies before first token.
- Engine dies mid-stream.
- Sidecar dies mid-stream.
- Event source disconnects.
- KV event replay gap.
- Duplicate KV events.
- Out-of-order events.
- Cancellation races with completion.
- Cancellation during KV transfer.
- Migration after partial output.
- Drain with in-flight requests.

## Risks and design constraints

- The event contract becomes the real API surface. Treat it as a versioned
  compatibility contract.
- Sidecar reduces build/runtime coupling but introduces semantic coupling to
  engine event semantics.
- Upstream engine teams may not prioritize Dynamo-specific event semantics
  unless the contract is shared and tested.
- Debugging may become harder if missing or reordered events trigger incorrect
  routing or capacity state.
- Sidecar may lose direct lifecycle control that current wrappers or unified
  backend have.
- Performance should be measured, not assumed. Sidecar may preserve native
  engine performance but can add serialization, event, tokenization, and
  control-plane overhead.
- Request migration should remain Dynamo-side in v1. Do not require
  engine-native migration state export/import.
- The sidecar path should not become an LLM-D clone. Dynamo must still provide
  differentiated value through routing, KV indexing, distributed runtime,
  NIXL/KVBM integration, planner, operator, and fault tolerance.
