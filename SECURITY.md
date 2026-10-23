# Security policy

Report vulnerabilities through a private GitHub security advisory rather than
a public issue.

The Bridge is local-first. Run it on the AEDT host and use SSH for remote
operation. Do not expose raw AEDT automation endpoints to untrusted networks.
Official Python runs through `native.execute` with exact SDK/session binding,
Runtime admission and explicit validation. Normal imports and builtins are
available to trusted agents; this path is not a hostile-code sandbox. Cancellation
only terminates task-owned workers and preserves existing user sessions.

Never attach customer projects, license logs, credentials, private host
addresses, or vendor documentation to a public issue.
