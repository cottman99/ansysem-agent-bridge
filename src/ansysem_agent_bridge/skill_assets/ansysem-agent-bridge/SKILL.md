---
name: ansysem-agent-bridge
description: "Inspect and operate an exact local or SSH-hosted Ansys Electronics Desktop target through the installed ansysem-agent Bridge. Use for Bridge setup and diagnosis, runtime profiles, project-bundle checks, runtime snapshots, capability discovery, bounded HFSS 3D Layout readback, typed transactions, resumable candidate workspaces, image export, and safe session handling. Route documentation-only questions to ansysem-kb-docs when that optional Skill is installed."
---

# AnsysEM Agent Bridge

Use `ansysem-agent` as the stable public interface. Run it on the AEDT host;
for remote work, invoke it through SSH rather than exposing a raw AEDT or
Bridge endpoint.

## Route the request

- Pure documentation or API research belongs to `$ansysem-kb-docs` and must
  not launch AEDT.
- Setup, project identity, live state, capability discovery, bounded execution,
  artifact export, and session lifetime belong here.
- For a combined task, establish the version-matched documented route first,
  then require a separate runtime acceptance gate.

## Establish one exact target

Start read-only:

```text
ansysem-agent --pretty doctor
ansysem-agent --pretty instances list
ansysem-agent --pretty project inspect --project <exact.aedt>
ansysem-agent --pretty runtime-snapshot --project <exact.aedt> --version <version>
```

Before live mutation, require one named profile whose exact Python, display,
module paths, and environment are ready:

```text
ansysem-agent --pretty profiles show <profile-id>
```

Preserve these identities:

```text
host + AEDT installation/version + display + process/session
+ .aedt/.aedb project bundle + project + design + editor + execution lane
```

Do not silently choose the newest installation, another project, or another
design. A `.aedt` file without its required `.aedb/edb.def` is not a complete
HFSS 3D Layout project bundle.

## Use capability state before execution

Inspect `declared`, `compatible`, `available`, `healthy`, and `authorized`
separately. A failed call does not prove that AEDT lacks an API. Distinguish a
wrong symbol, version mismatch, unavailable Python environment, stale object
identity, missing model prerequisite, unhealthy session, and missing
authorization before changing lanes.

Prefer, in order:

1. a maintained Bridge semantic operation;
2. a version-verified PyAEDT, PyEDB, or native AEDT adapter owned by the Bridge;
3. bounded GUI assistance only when the API lanes are proven inadequate and
   the action has independent readback.

Do not use blind coordinates, stale screenshots, or GUI appearance as solver
evidence.

Once a matching Bridge capability is available, call it through its typed JSON
contract. Do not recreate the same vendor operation in one-off SSH Python or GUI
steps. Reuse an unchanged runtime `state_revision`; do not repeat environment,
module, window, or object-tree probes without a state change or new evidence need.

## Bound execution and evidence

Use live operations only for the exact project and intended display. A live
snapshot proves captured state, not a later mutation or solve. After any state
change, require object/property readback and the workflow's geometry,
electrical, AEDT-validation, solver-input, or numerical gate as applicable.

Image export is presentation evidence only:

```text
ansysem-agent --pretty --profile <profile-id> layout export-image \
  --project <exact.aedt> --version <version> --output <new.png>
```

Never overwrite customer input or publish local project paths, credentials,
license details, vendor documentation, or customer artifacts.

For a mutation, compile task-specific values into typed JSON. Do not put those
values into this Skill or add a task-specific Bridge command. Use only registered
operations and assertions and keep `solve_requested` false. For bondwire work,
use the PyEDB-native adapter, exact object identity and `expected_before`, and
typed APD fields; never pass a raw APD block or vendor call.

Use one-shot `ansysem-operation-plan/v1` only when the complete final change is
already known:

```text
ansysem-agent --pretty --profile <profile-id> \
  model apply --plan - --redact-paths < <operation-plan.json>
```

If the task may need observation and correction, begin one candidate workspace
from the frozen source. Keep all attempts there; a reconcile checkpoint is not a
model version. Submit stable patch IDs and the last returned workspace revision.
An identical retry returning `preserved` must not trigger another EDA call.
Within one observation-and-correction cycle, batch all already-known compatible
edits and their assertions into one patch; do not pay for one fresh reopen per
object unless an earlier result is genuinely needed to decide the next edit.

```text
ansysem-agent --pretty --profile <profile-id> model workspace begin \
  --source <frozen.aedt> --workspace <candidate-dir> \
  --adapter <adapter-id> --version <version> --design <design>
ansysem-agent --pretty --profile <profile-id> model workspace reconcile \
  --workspace <candidate-dir> --plan - < <patch.json>
```

Use `rollback` for a bad committed checkpoint and `abort` to discard owned
candidate generations. Do not create a new external version merely because a
patch or assertion failed. Only an explicit `workspace promote` may create the
delivery output; it must cleanly replay the journal from the frozen source and
pass the final fresh-reopen registry. The mutable candidate is not delivery
evidence. Supply a stable promotion ID so a lost response can be retried as
`preserved` without another EDA call. If status reports an interrupted
promotion, retry the exact recorded promotion request. The Bridge will verify an
already-complete output or remove only the recorded partial output and staging
area before replaying; do not create a replacement workspace or output version.

Treat a one-shot apply or promotion as successful only when JSON status and
process exit code agree, source integrity is preserved, the output bundle is
complete, and every final assertion passed. After the same semantic failure is
observed twice, stop issuing mutations and re-check capability, target identity,
preconditions, and the plan rather than accumulating retries.

Stop after returning the exact identity, assertions, output hash, and evidence
boundary. Do not solve, package, publish, create a release, or add extra visual
assets unless the user explicitly requests that separate phase.

## Finish cleanly

Report the selected identity, capability state, actual readback, artifact
hashes, and remaining evidence boundary. Close only a session created and
verified as owned by the current operation; otherwise disconnect and leave the
user's AEDT process unchanged.
