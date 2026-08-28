# Generic Runtime and AEDT Context

The optional `eda-bridge-runtime` integration gives local and SSH callers the
same request envelope and ledger. The Agent supplies a concise purpose. Runtime
and Bridge events inherit it and record observed phase timing separately.

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

## Context Add-in

The Add-in uses PyAEDT's supported `add_script_to_menu()` registration under
`PersonalLib/Toolkits/Project/TabConfig.xml`. It owns only three named actions
in PyAEDT's supported Automation panel and can report or remove that exact
scope.

Each capture writes the exact active project/design identity to the private
AnsysEM Agent runtime directory and places a checksummed `EDA_CONTEXT/v1` token
on the clipboard. The token contains no project path or credentials. Runtime
resolution rejects missing or stale generations.
