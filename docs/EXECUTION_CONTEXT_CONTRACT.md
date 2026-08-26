# Agent execution context contract

Status: alpha.

## Boundary

The Bridge owns bounded Ansys Electronics Desktop runtime facts, target
identity, capability state, semantic operations, artifacts, and readback. It
does not own Agent planning, project workflow policy, engineering memory, or
knowledge promotion.

The Bridge publishes four versioned contracts:

- `ansysem-target-identity/v1`
- `ansysem-runtime-snapshot/v1`
- `ansysem-capability-descriptor/v1`
- `ansysem-operation-result/v1`

## Target rule

Every live claim preserves the host, AEDT installation and version, display,
process or session, `.aedt` plus `.aedb` project bundle, project, design,
editor, and execution lane. A caller must not infer a missing identity from the
foreground window or silently switch a running session.

## Capability rule

Every capability separates whether it is declared, compatible with the
selected runtime, currently available, healthy, and authorized. A caller must
inspect those fields instead of learning support by repeatedly executing
arbitrary code.

## Performance rule

Prefer one compact runtime snapshot over repeated installation, project,
module, window, and capability probes. Reuse `state_revision` to suppress
unchanged state. Screenshots, complete object trees, full logs, and solver
artifacts are separate evidence requests.

## Evidence rule

A live snapshot is capture-time state, not evidence that a later mutation or
solve succeeded. A project file is not a complete HFSS 3D Layout bundle unless
the associated `.aedb/edb.def` is present. Visual output is presentation
evidence, not electrical or solver evidence.
