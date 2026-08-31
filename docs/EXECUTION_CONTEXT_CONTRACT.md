# Agent execution context contract

Status: alpha.

## Boundary

The Bridge owns bounded Ansys Electronics Desktop runtime facts, target
identity, capability state, semantic operations, artifacts, and readback. It
does not own Agent planning, project workflow policy, engineering memory, or
knowledge promotion.

The Bridge publishes seven versioned contracts:

- `ansysem-target-identity/v1`
- `ansysem-runtime-snapshot/v1`
- `ansysem-capability-descriptor/v1`
- `ansysem-operation-result/v1`
- `ansysem-operation-plan/v1`
- `ansysem-workspace-patch/v1`
- `ansysem-continuation-context-record/v1` (private host record)

## Runtime profile rule

A live mutation uses one named runtime profile that records the exact Python
executable, graphical display, module paths, and bounded environment changes.
The Bridge validates the interpreter entry point and, when needed, performs a
controlled re-execution of its own fixed CLI so loader variables take effect
before PyAEDT or AEDT libraries are imported. It accepts no shell command,
module name, or arbitrary Python field from the caller.

The CLI writes exactly one machine-readable JSON document to standard output.
Vendor progress and diagnostics are routed to standard error so callers never
need to scrape JSON from a mixed stream.

## Transaction rule

A typed mutation never overwrites its source. The Bridge copies the complete
project bundle to an owned staging area, applies only registered semantic
operations, saves and closes its owned session, then verifies typed assertions
after a separate fresh reopen. Only a passing bundle is moved to the new output
path. Failure removes only transaction-owned staging and partial output.

## Candidate workspace rule

An iterative task uses one Bridge-owned workspace. Typed patches carry stable
IDs and the expected workspace revision. Passing patches become internal
checkpoints, not external model versions. Rollback and abort affect only owned
generations. Promotion is explicit and creates a new output only after replaying
the journal from the frozen source and passing the final fresh-reopen assertions.
The mutable candidate is never promoted by copying it directly.
Promotion intent is persisted before EDA starts. An interrupted exact retry
verifies a complete output without reapplying mutation, or cleans only the
intent-owned partial output and staging directory before replaying.

## Target rule

Every live claim preserves the host, AEDT installation and version, display,
process or session, `.aedt` plus `.aedb` project bundle, project, design,
editor, and execution lane. A caller must not infer a missing identity from the
foreground window or silently switch a running session.

## Continuation rule

A complete project capture records its exact host path, bundle SHA-256, cheap
content-state revision, profile, version, design, and Display inside the private
AEDT-host registry. Its `EDA_CONTEXT` remains an opaque locator and does not
contain the private path or either fingerprint. Legacy contexts remain usable by
operations that do not require content materialization; governed native
continuation requires a newly captured content-bound record.

For `native.batch`, the trusted Bridge may materialize the fixed runtime,
resource kind, bound version/design selectors, the one source read path, and the
mutation source fingerprint. Any explicit conflicting value is rejected. The
Bridge never infers effect, write paths, artifacts, transaction strategy,
fresh-reopen or promotion policy, engineering validation, limits, purpose, or
idempotency. Observe returns the unchanged opaque context; a passing staged
mutation returns a new output-bound `continuation_context`. The accompanying
`continuation_state` contains no path or fingerprint.

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

Use compact state revisions and copy-on-write where available for candidate
continuity. Reserve full bundle hashing and the complete assertion registry for
explicit promotion. Stream JSON through standard input when this avoids creating
and transferring one-off remote scripts without weakening the typed contract.

## Evidence rule

A live snapshot is capture-time state, not evidence that a later mutation or
solve succeeded. A project file is not a complete HFSS 3D Layout bundle unless
the associated `.aedb/edb.def` is present. Visual output is presentation
evidence, not electrical or solver evidence.
