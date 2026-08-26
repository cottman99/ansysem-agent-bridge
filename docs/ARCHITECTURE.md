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
7. **Persisted state before success.** Mutations use a new output bundle and
   pass only after save, owned-session close, fresh reopen, and typed assertions.
8. **Compact by default.** Runtime snapshots are revisioned; operations return
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

Every stateful semantic operation passes these gates:

1. resolve exact target and expected preconditions;
2. inspect capability descriptor and authorization;
3. compile intent into a typed adapter request;
4. copy the complete source bundle to an owned, non-overwriting staging path;
5. execute with an operation ID and bounded registered adapter;
6. save, close the owned session, and reopen in a separate fresh session;
7. read back typed assertions using the correct object-ID domain;
8. commit the new output bundle only after every assertion passes;
9. return `ansysem-operation-result/v1` and clean up owned resources.

The alpha implements the read-only/static gates, live HFSS 3D Layout snapshot,
native layout image export, and one narrow transaction adapter. Its registered
mutations are exact `BaseElementTab` property changes and semantic outer-edge
gap-port creation with a typed reference patch. Arbitrary geometry, stackup,
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
