# Architecture

## Product boundary

AnsysEM Agent Bridge is a local control plane between a general-purpose Agent
and one explicitly selected Ansys Electronics Desktop runtime. It binds intent
to an exact Context, selects the version-matched official runtime or a
certified workflow, and
returns machine-readable identity, readback, validation, artifacts, warnings,
and safe next actions.

The package also carries an independent Bootstrap Experience Library. It gives
a new Agent a small version-scoped starting point, but is neither execution
logic nor durable engineering memory. Official docs remain authoritative;
missing experience only degrades guidance.

The Bridge is useful without a Harness. A Harness may later compose workflows,
approvals, durable engineering memory, budgets, and promotion policy around the
same contracts. Skills teach an Agent when and how to call the Bridge; they do
not contain transport logic or vendor-specific implementation code.

```text
Agent / CLI caller
       |
       | stable JSON contracts
       v
intent gate -> target resolver -> capability registry -> semantic operation
                                                        |
                    +----------------+-------------------+----------------+
                    |                |                   |                |
              local docs      static bundle       PyEDB/PyAEDT      native AEDT
                    |                |                   |                |
                    +----------------+-------------------+----------------+
                                                        |
                                      readback + validation + artifacts
```

## Top-level rules

1. **Identity before action.** Host, release, display, process/session,
   project bundle, project, design, editor, and lane form one target tuple.
2. **Capability before probing.** `declared`, `compatible`, `available`,
   `healthy`, and `authorized` are independent facts. One missing search hit or
   failed call never proves that no API exists.
3. **Official API reach before wrapper growth.** Use version-matched docs and a
   governed PyAEDT/PyEDB/native batch for new EDA functionality. Stable semantic
   operations are certified workflows or infrastructure, not a replacement API.
   A certified workflow is only an asset-bound compiled shortcut; asset
   id/version/hash and applicability are verified before it becomes preferred.
4. **Readback before success.** A returned success boolean is insufficient.
   Results include the selected identity and operation-specific state or an
   artifact hash.
5. **Evidence is typed.** Documentation, file, live-editor, geometry,
   electrical, solver-input, convergence, and numerical evidence are not
   interchangeable.
6. **Lifecycle is owned.** A command closes only a session it created. It never
   force-kills an unverified process or silently discards another user's work.
7. **Attempts are not revisions.** Iterative work stays in one candidate
   workspace. Only explicit clean-replay promotion creates a permanent output.
8. **Desired state before retry.** Registered adapters first detect an already
   satisfied request; an identical patch never repeats an EDA mutation.
9. **Assurance matches the gate.** Reconcile uses scoped persisted-state
   assertions; promotion performs the full source-to-output assurance gate once.
10. **Compact by default.** Runtime snapshots are revisioned; operations return
   counts and hashes instead of repeating full trees or logs.

## Route selection

The route is selected by required semantics, not convenience:

| Need | Preferred lane | Stop condition |
| --- | --- | --- |
| Find a documented symbol or limitation | version-matched local docs | Evidence remains documentation-only |
| Check files, hashes, or bundle completeness | static host adapter | Never claim live AEDT state |
| Read or edit EDB concepts offline | eligible compiled shortcut or governed PyEDB batch | Require complete EDB and post-operation readback |
| Read or edit an AEDT design | eligible compiled shortcut or governed PyAEDT/native batch | Require exact runtime identity and health |
| Perform a native operation missing in PyAEDT | narrow native AEDT adapter | Preserve native identifiers and release tests |
| Assist with a genuinely UI-only action | bounded visual assistance | Only after API lanes are disproved; independent readback is mandatory |

GUI automation is therefore an explicit last lane, not an automatic fallback.

## Request lifecycle

Agent-facing local and SSH requests first enter `eda-bridge-runtime`. A short
declared purpose and automatically detected identity are recorded before an EDA
adapter runs. AnsysEM operations are durable jobs: submission, worker execution,
and observation are independent phases linked by request, run, job, and trace
identities. SSH disconnection does not authorize replay and does not define job
failure.

The AEDT Automation-tab Context Add-in creates bounded `EDA_CONTEXT/v2`
snapshots with origin, session, Display, project/design name, capabilities,
and freshness. Full project paths stay in a private host registry and are
resolved by the AnsysEM adapter inside the submitted operation. Legacy v1
remains accepted. The Context protocol belongs to the generic Runtime; active
AEDT discovery belongs to this Bridge.

When the selected project is a complete bundle, that private record also binds
the exact bundle digest and a lightweight content-state revision to the existing
profile, version, design, and Display identity. The opaque token carries neither
the path nor those fingerprints. A context-driven `native.batch` may omit only
the fixed source-identity fields: the Bridge materializes them before durable
job submission, rejects explicit conflicts, and refuses a changed bundle. The
Agent still declares purpose, effect, program, write/artifact scope, transaction
policy, validation, limits, and mutation idempotency. A passing operation returns
an opaque `continuation_context` plus a non-sensitive `continuation_state`.

For a fully known one-shot mutation, the Bridge copies the frozen source to an
owned stage, applies registered operations, saves and closes its session,
performs fresh-reopen assertions, and non-destructively commits a distinct
two-part project bundle. Normal failures remove partial output, but one-shot
apply does not provide the durable interruption-resume contract of a workspace.

For iterative work, the lifecycle is:

1. resolve one frozen source, runtime profile, adapter, design, and candidate
   workspace for the task;
2. compile each bounded correction into an idempotent typed patch with the last
   workspace revision;
3. apply and fresh-reopen only the patch's scoped assertions, then commit an
   internal checkpoint;
4. roll back inside that workspace when required instead of creating a new
   external version;
5. at the explicit delivery gate, record an exact promotion intent, replay the
   typed journal from the frozen source, and run the complete final assertion
   registry;
6. commit one non-overwriting output and retain machine-readable evidence;
7. after interruption, accept only the exact recorded request, then either
   verify the complete output without mutation or clean only its owned partial
   output and stage before replaying.

The alpha implements the read-only/static gates, live HFSS 3D Layout snapshot,
native layout image export, native property/gap-port and PyEDB bondwire
transaction adapters, candidate workspace lifecycle, and a governed official
PyAEDT batch with declared scope, source fingerprint, timeout, staging,
fresh-reopen validation, and promotion. Its policy lint is an accidental-risk
boundary, not a hostile-code security sandbox.

## Failure model

- `blocked`: a known prerequisite is absent; the operation did not start.
- `attention_required`: useful evidence was captured, but an optional or
  requested validation gate failed or is unsupported.
- `failed`: execution began but the promised result was not produced.
- `passed`: execution and the declared validation gates completed.

Failures carry a stable reason, the evidence already obtained, and safe next
actions. Adapter exceptions must not erase a valid target snapshot.

## Capability growth and workflow promotion

The shared [EDA capability model](https://github.com/cottman99/eda-bridge-runtime/blob/main/docs/CAPABILITY_MODEL.md)
defines five distinct coverage dimensions and four operation classes. New
official API uses normally belong in governed native execution. The reusable
abstractions are Context, batch, staging, fingerprint, idempotency, pre/post
assertions, fresh reopen, artifact validation, and promotion.

A high-frequency recipe is promoted to a certified workflow only when it has:

- a semantic name and versioned input/output contract;
- explicit target, version, lane, safety, and mutation metadata;
- preconditions and authorization behavior;
- release-specific adapter tests;
- object/property readback and the correct validation layer;
- redaction, timeout, retry/idempotency, and owned-session cleanup behavior;
- synthetic CI coverage plus a sanitized real-runtime acceptance record.
- an eligible packaged experience asset whose id, version, hash,
  applicability, effect, parameters, validation, and governed-native fallback
  match the compiled implementation;
- a receipt containing that binding and the expanded-plan hash.

One missing geometry primitive, plot kind, or solver option does not justify a
new workflow. This rule keeps the public workflow surface small while the
official API remains broadly reachable through the governed lane.
