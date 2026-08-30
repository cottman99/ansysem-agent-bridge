# Operation classification audit

This audit applies the shared EDA capability model to the current AnsysEM
Bridge. It changes architectural meaning, not compatibility: accepted typed
workflows remain available while common execution and transaction mechanics are
generalized.

| Operation family | Class | Decision |
| --- | --- | --- |
| `docs.status/query/get` | Bridge infrastructure | Keep; version-matched documentation is the knowledge path for official APIs |
| `project.inspect/create` | Bridge infrastructure | Keep; exact bundle identity and non-overwrite creation are foundational |
| `runtime.snapshot` | Bridge infrastructure | Keep; static and live identity evidence remain distinct |
| `session.launch/release` | Bridge infrastructure | Keep; Runtime-owned AEDT lifecycle is core |
| `workspace.begin/status/reconcile/rollback/abort/promote` | Bridge infrastructure | Keep and generalize; candidate continuity, checkpoints, replay, and promotion are reusable transaction mechanics |
| `layout.export_image` | Bridge infrastructure / artifact readback | Keep as a native evidence mechanism, not as layout feature coverage |
| `layout.build` | Certified workflow | Keep as the accepted bounded HFSS 3D Layout build recipe; do not add one wrapper per primitive or port family |
| `layout.solve` | Certified workflow | Keep as the accepted explicit-sweep result recipe; extract generic job, artifact, numeric, and fresh-reopen validation |
| `model.apply` and its bondwire/property recipes | Certified workflow | Keep compatible; extract staging, fingerprint, official-runtime batch, assertions, and promotion rather than growing its operation vocabulary |
| internal live probes and synthetic geometry checks | Acceptance probe | Keep behind the public operations that need them; do not count probes as product breadth |

## Coverage status after the audit

- **Knowledge coverage:** configured version-matched AnsysEM documentation with
  bounded retrieval evidence.
- **Official API reach:** PyAEDT, PyEDB, and native AEDT APIs are installed and
  used by adapters, but not yet exposed through one governed general contract.
- **Generic execution coverage:** absent from the default public surface; new
  official API uses currently require Bridge code, which is the key gap.
- **Default supported coverage:** infrastructure plus the maintained certified
  HFSS 3D Layout workflows.
- **Validated workflow coverage:** the retained build, solve, transaction,
  bondwire, lifecycle, and workspace acceptances only.
