---
name: ansysem-agent-bridge
description: Operate exact Ansys Electronics Desktop or EDB targets through official PyAEDT/PyEDB using EDA Runtime; use for live sessions, isolated projects, offline databases, setup and native validation.
---

# AnsysEM Agent Bridge

Use `docs.symbol` with `sdk=pyaedt` or `sdk=pyedb` to inspect installed source
signatures and docstrings without importing modules or evaluating getters.

Use Runtime for Agent execution; CLI commands provide setup, administration and
direct diagnostics. Every request carries a concise purpose. A known task and
Context are enough to execute its known contract; do not repeat broad discovery.
Use `$ansysem-kb-docs` for documentation-only questions without launching AEDT.

Preserve host, installation/version, display, project, design and session identity.
HFSS 3D Layout projects include the `.aedt` and matching `.aedb` bundle. Select an
exact runtime profile when it supplies the Python environment and library paths.
Never silently choose the latest version or a foreground project.

| Runtime | Modes | Official object |
| --- | --- | --- |
| `ansys.pyaedt.hfss3dlayout` | live, background | PyAEDT `Hfss3dLayout` |
| `ansys.pyedb` | offline | PyEDB `Edb` |

These are maintained host bindings, not a claim that every AEDT application backend
has been implemented. An unwrapped method within these SDKs needs no Bridge change.

Use `native.execute` with schema `eda.native-program/v1`. Choose `runtime`, `mode`
and `effect` separately. Both observe and mutate programs use `eda.submit` with a
stable idempotency key. Normal imports, builtins and installed dependencies work.
The program defines `run(api, context)` and returns a JSON object; `api` is the
official object above. Mutation validation defines `validate(api, context)` and
returns `status: passed` with native readback facts.

Live execution binds a captured Context or the exact owned session's `resource_id`
and `release_handle`. It verifies process, project and design, uses transaction
strategy `none`, and detaches without closing that session. Save explicitly when
durable persistence is required. A live failure does not imply automatic rollback.

Background/offline mutation uses `adapter_staging`, fingerprints for every input,
`fresh_reopen: true` and `promotion: on_validation`. It saves, closes, reopens and
validates the candidate before promoting a new output. Source and destination differ.
Observe programs use no write paths and do not promote output.

`project.create` creates a new 3D Layout project. `session.launch` creates an owned
GUI session; use its returned typed release fields when finished. User-owned or
reused sessions stay open. Retained model/workspace workflows run through the same
Runtime admission; they are optional conveniences, not the official capability limit.

Use `docs.query` and `docs.get` through `eda.read` for exact version-matched evidence.
Raw HTML, Markdown, RST and SDK Python/stubs can prepare automatically into a private
cache. Source signatures and docstrings are inspected without importing source code.
Missing Markdown or experience never blocks native execution. A missing symbol in
search is not evidence of missing permission; distinguish environment, version,
target identity, API signature and task authorization from each other.

Accepted jobs are pending. Wait for a terminal receipt; after timeout/disconnect use
status, events or the existing run ID. Never replay uncertain work with a new key.
Report native readback and engineering/solver validation separately. GUI appearance
or exported images alone do not prove electrical or numerical correctness.
