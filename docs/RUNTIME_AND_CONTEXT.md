# Generic Runtime and AEDT Context

The automatically installed `eda-bridge-runtime` integration gives local and SSH callers the
same request envelope and ledger. The Agent supplies a concise purpose. Runtime
and Bridge events inherit it and record observed phase timing separately.

The Runtime Skill, MCP server, and connection registry run on the Agent host.
`ansysem-agent runtime serve`, the durable worker, AEDT add-in, and AEDT run on
the EDA host. On a combined host the same adapter is selected through a local
connection. Capabilities report `execution_host_role=eda-worker` and
`run_model=durable`.

## Durable remote work

`ansysem-agent runtime serve` is a long-lived JSON-lines endpoint suitable for
the generic SSH stdio transport. A normal AnsysEM request is persisted in the
job database before a detached worker starts. The worker re-enters the existing
named runtime profile, so AEDT libraries are not imported under an accidental
Python, display, or library path.

Transport delivery is at-least-once. Mutations require an idempotency key. The
same key and operation returns the original job; the same key with different
content is rejected. A dropped SSH connection never triggers blind mutation
replay.

Submission, status, and incremental-event responses retain the original job
Run identity. The Agent-side Runtime projects them into the same compact Run
view used for synchronous bridges, so a successful status query is not confused
with completion of the underlying AEDT job.

The profile selected by the registered Runtime connection is inherited by
detached workers automatically. Agents do not repeat installation or display
environment details on every durable request.

An explicitly launched `session.launch` resource may be reused by a live
`runtime.snapshot` only when its opaque `resource_id` and handle authorize an
active Runtime-owned AEDT process and the recorded project, version, design,
process id, and private gRPC port all match. The port is never selected or
exposed by the Agent. Reuse attaches, reads, and detaches without closing the
desktop; `session.release` remains the only operation that can close it. This
is a Bridge-infrastructure optimization, not a shortcut for an HFSS task.

For a greenfield task, the AnsysEM Skill establishes the typed `project.create`
operation without requiring an existing context; capability discovery is used
only when that contract is unknown or stale. The operation creates one isolated
HFSS 3D Layout Bundle, saves and closes it, verifies it in a fresh AEDT
session, and returns an opaque context that can immediately drive operations
such as `project.inspect`. The exact remote project path stays in the private
host-side context record.

## Context Add-in

The Add-in uses PyAEDT's supported `add_script_to_menu()` registration under
`PersonalLib/Toolkits/Project/TabConfig.xml`. When a live AEDT identity is supplied,
the installer queries that session for its actual PersonalLib instead of guessing from
the operating-system account. It owns only three named actions
in PyAEDT's supported Automation panel and can report or remove that exact
scope.

Each capture writes the exact active project/design identity to the private
AnsysEM Agent runtime directory and places a checksummed, bounded
`EDA_CONTEXT/v2` snapshot on the clipboard. It carries origin, live-session
identity, Display, project/design names, version, capability digest, and
freshness while keeping the full project path and credentials out of the
token. Runtime accepts legacy v1 tokens and the adapter rejects missing or
stale generations.

For a complete `.aedt` plus `.aedb/edb.def` bundle, the private record also
stores its full bundle digest and lightweight state revision. A later governed
native request can therefore pass the opaque Context and omit repeated
source-identity bookkeeping. The Bridge fills only the bound runtime,
resource kind, version/design selectors, read path, and mutation source
fingerprint, then checks the captured state before accepting the durable job.
Explicit identity or fingerprint conflicts fail closed. The plan still carries
all engineering and safety choices. Success returns `continuation_context` and
a bounded `continuation_state`; `eda_context` remains as a compatibility alias.
