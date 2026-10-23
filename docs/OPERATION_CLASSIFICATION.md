# Operation classification audit

This audit applies the shared EDA capability model to the current AnsysEM
Bridge. It changes architectural meaning, not compatibility: accepted typed
workflows remain available while common execution and transaction mechanics are
generalized.

| Operation family | Class | Decision |
| --- | --- | --- |
| `docs.status/query/get` | Bridge infrastructure | Keep; version-matched documentation is the knowledge path for official APIs |
| `experience.list/get` | Bridge infrastructure | Keep as a read-only advisory gateway; missing assets never block execution |
| `project.inspect/create` | Bridge infrastructure | Keep; exact bundle identity and non-overwrite creation are foundational |
| `runtime.snapshot` | Bridge infrastructure | Keep; static and live identity evidence remain distinct |
| `session.launch/release` | Bridge infrastructure | Keep; Runtime-owned AEDT lifecycle is core |
| `workspace.begin/status/reconcile/rollback/abort/promote` | Bridge infrastructure | Keep and generalize; candidate continuity, checkpoints, replay, and promotion are reusable transaction mechanics |
| `layout.export_image` | Bridge infrastructure / artifact readback | Keep as a native evidence mechanism, not as layout feature coverage |
| `native.execute` | Generic native execution | Primary official PyAEDT extension path with declared scope, timeout, staging, fresh reopen, and promotion |
| `layout.build` | Compatibility shortcut | Keep callable only for experience-referenced background recipes; its mini geometry vocabulary is not the default extension path and must not grow |
| `layout.solve` | Provisional compiled shortcut | Keep compatible while its experience binding and same-task advantage remain evidenced; extract generic job, artifact, numeric, and fresh-reopen validation |
| `model.apply` and its bondwire/property recipes | Compatibility shortcut | Keep callable for bound experience assets; use governed native execution for new properties or objects rather than growing the wrapper vocabulary |
| internal live probes and synthetic geometry checks | Acceptance probe | Keep behind the public operations that need them; do not count probes as product breadth |

## Coverage status after the audit

- **Knowledge coverage:** configured version-matched AnsysEM documentation with
  bounded retrieval evidence.
- **Official API reach:** official HFSS 3D Layout PyAEDT is reachable through a
  governed general contract; PyEDB and other AEDT products remain future lanes.
- **Generic execution coverage:** observe and staged mutation include source
  fingerprint, timeout, fresh reopen, validation, and promotion on supported
  Windows and Linux hosts; this is not a hostile-code sandbox.
- **Default supported coverage:** infrastructure plus the maintained certified
  HFSS 3D Layout workflows.
- **Validated workflow coverage:** the retained build, solve, transaction,
  bondwire, lifecycle, and workspace acceptances only.

The native backend registry now distinguishes live/background HFSS 3D Layout and offline PyEDB. Process supervision is portable and does not depend on POSIX signals. Real EDA acceptance is recorded per platform and mode; portability alone does not prove every installation.
