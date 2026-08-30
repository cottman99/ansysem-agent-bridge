# Capability, mechanism, and evidence matrix

| User task | Bridge mechanism | Alpha status | Boundary |
| --- | --- | --- | --- |
| Discover configured AEDT installations | Environment and explicit local configuration | Implemented | Never silently chooses among multiple installations |
| Verify an HFSS 3D Layout project bundle | `.aedt` hash plus `.aedb/edb.def` presence | Implemented | Does not prove design or solver correctness |
| Inspect current capability state | Versioned capability descriptors | Implemented | Static declaration and dynamic availability remain separate |
| Start from no project through the generic Runtime | Typed `project.create` creates one non-existing HFSS 3D Layout bundle, saves and closes it, performs a fresh AEDT reopen, and returns an opaque `EDA_CONTEXT` | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 / Linux / `DISPLAY=:4.0` | HFSS 3D Layout only; refuses overwrite, does not solve, and does not expose the remote project path in the token |
| Expose AnsysEM as an EDA worker to a local or remote Agent host | Runtime capabilities report `execution_host_role=eda-worker` and `run_model=durable`; job status and event responses preserve the original Run identity; detached workers inherit the registered connection profile | Unit-tested and validated through the installed Agent-host Runtime over SSH on AEDT 2026.1 / Linux / `DISPLAY=:4.0` | Agent-side Skill/MCP files are not required on an EDA-only host; detached execution remains host-side |
| Capture a compact host/project snapshot | Revision-aware runtime snapshot | Implemented | Host snapshot is not live AEDT proof |
| Read live HFSS 3D Layout identity | Bounded PyAEDT live probe | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 on Linux | Opens only an explicit complete project bundle and closes only its own new session |
| Export an HFSS 3D Layout image | Native editor `ZoomToFit` and `ExportImage` behind a bounded adapter | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 on Linux | Image is presentation evidence only |
| Build a bounded HFSS 3D Layout design from an empty project | Typed materials, bottom-to-top stackup, rectangles, traces, edge ports, and setup through PyEDB; matching AEDT save and fresh PyEDB/AEDT reopens | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 / PyEDB 0.82.0 / Linux / `DISPLAY=:4.0` | v1 supports the declared primitive and edge-port families, not arbitrary modeler calls or every HFSS 3D Layout feature |
| Solve an explicit sweep and return usable results | Typed named discrete sweep, blocking AEDT analysis, finite numeric readback, CSV export, native report creation, source preservation, and fresh AEDT reopen | Validated with a five-point synthetic two-port acceptance on AEDT 2026.1.0 / PyAEDT 1.4.0 / Linux / `DISPLAY=:4.0` | Proves workflow execution and persisted evidence, not RF accuracy, convergence quality, or suitability of an untuned synthetic design |
| Apply a typed HFSS 3D Layout transaction | Named runtime profile plus non-overwriting copy, registered native operations, save/close, fresh reopen, and assertions | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 on Linux | Current v1 operations are exact property changes and semantic outer-edge gap-port creation; no solve or packaging |
| Apply a typed bondwire transaction | Source fingerprints plus PyEDB mutation, AEDT save/close, fresh AEDT and PyEDB reopens, and geometric assertions | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 / PyEDB 0.82.0 on Linux | Structured APD profiles and exact-name bondwire changes only; no raw APD block, arbitrary call, solve, or packaging |
| Iterate without creating a version per attempt | One candidate workspace, optimistic revision, idempotent typed patch journal, internal checkpoints, rollback/abort, durable promotion intent, and explicit clean-replay promotion | Validated on AEDT 2026.1.0 / PyAEDT 1.4.0 / PyEDB 0.82.0 on Linux; interruption paths are synthetic-tested | Candidate checkpoints are not delivery revisions; the selected adapter still limits available mutations |
| Query local version-matched documentation | Configured private corpus and bounded source references | Implemented | Documentation is not redistributed or treated as runtime proof |
| Create or repair arbitrary geometry, port families, meshing, or solver features outside a versioned plan | Not claimed | Not claimed | The public surface stays typed and bounded; unsupported families require a reviewed adapter extension rather than raw Python |
| General GUI automation | Not claimed | Not claimed | No blind coordinate or screenshot-only success path |

Unit tests protect public contracts and failure behavior. Real AEDT validation
is reported separately and does not broaden untested product claims.

`ValidateDesign` raised a PyAEDT gRPC API error in the Linux acceptance. The
Bridge preserves prior live readback and reports `attention_required`; it does
not claim that validation passed. See the
[sanitized acceptance record](VALIDATION_AEDT_2026R1_LINUX.md).
