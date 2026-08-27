# Architecture

## Product boundary

AnsysEM Agent Bridge is a local control plane between a general-purpose Agent
and one explicitly selected Ansys Electronics Desktop runtime. It converts an
intent into a bounded semantic operation, selects a verified adapter, and
returns machine-readable identity, readback, validation, artifacts, warnings,
and safe next actions.

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
3. **Semantic operations before raw execution.** Public commands express a
   stable task such as `project.inspect` or `layout.export_image`; adapters own
   release-specific signatures and object-ID conversions.
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
| Read or edit EDB concepts offline | typed PyEDB adapter | Require complete EDB and post-operation readback |
| Read or edit an open AEDT design | typed PyAEDT/native adapter | Require exact runtime identity and health |
| Perform a native operation missing in PyAEDT | narrow native AEDT adapter | Preserve native identifiers and release tests |
| Assist with a genuinely UI-only action | bounded visual assistance | Only after API lanes are disproved; independent readback is mandatory |

GUI automation is therefore an explicit last lane, not an automatic fallback.

## Request lifecycle

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
transaction adapters, plus the candidate workspace lifecycle. Arbitrary geometry, stackup,
setup, solver, command, module, or Python execution remains unclaimed.

## Failure model

- `blocked`: a known prerequisite is absent; the operation did not start.
- `attention_required`: useful evidence was captured, but an optional or
  requested validation gate failed or is unsupported.
- `failed`: execution began but the promised result was not produced.
- `passed`: execution and the declared validation gates completed.

Failures carry a stable reason, the evidence already obtained, and safe next
actions. Adapter exceptions must not erase a valid target snapshot.

## Extension rule

A new capability is promoted only when it has:

- a semantic name and versioned input/output contract;
- explicit target, version, lane, safety, and mutation metadata;
- preconditions and authorization behavior;
- release-specific adapter tests;
- object/property readback and the correct validation layer;
- redaction, timeout, retry/idempotency, and owned-session cleanup behavior;
- synthetic CI coverage plus a sanitized real-runtime acceptance record.

This promotion rule generalizes beyond any single API failure and keeps the
public surface smaller than the vendor API while still making it dependable.
