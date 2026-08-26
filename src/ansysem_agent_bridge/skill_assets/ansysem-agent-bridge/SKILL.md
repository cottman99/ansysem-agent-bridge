---
name: ansysem-agent-bridge
description: "Inspect and operate an exact local or SSH-hosted Ansys Electronics Desktop target through the installed ansysem-agent Bridge. Use for Bridge setup and diagnosis, runtime profiles, project-bundle checks, runtime snapshots, capability discovery, bounded HFSS 3D Layout readback, typed non-overwriting transactions, image export, and safe session handling. Route documentation-only questions to ansysem-kb-docs when that optional Skill is installed."
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

For a mutation, compile task-specific values into a project-local or disposable
`ansysem-operation-plan/v1`. Do not put those values into this Skill or add a
task-specific Bridge command. The plan may use only registered typed operations
and assertions; it must name distinct source and output bundles and set
`solve_requested` to false.

```text
ansysem-agent --pretty --profile <profile-id> \
  model apply --plan <operation-plan.json> --redact-paths
```

Treat the operation as successful only when the result is `passed`, the source
hashes are unchanged, the output bundle is complete, and every assertion passed
after save, owned-session close, and a separate fresh reopen. A zero process
exit code must agree with a successful JSON status.

Stop after returning the exact identity, assertions, output hash, and evidence
boundary. Do not solve, package, publish, create a release, or add extra visual
assets unless the user explicitly requests that separate phase.

## Finish cleanly

Report the selected identity, capability state, actual readback, artifact
hashes, and remaining evidence boundary. Close only a session created and
verified as owned by the current operation; otherwise disconnect and leave the
user's AEDT process unchanged.
