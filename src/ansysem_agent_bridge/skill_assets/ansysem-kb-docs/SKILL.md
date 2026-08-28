---
name: ansysem-kb-docs
description: "Retrieve version-matched evidence from a configured local Ansys Electronics Desktop documentation corpus. Use for documentation-only AEDT, PyAEDT, PyEDB, HFSS, HFSS 3D Layout, Maxwell, Q3D, SIwave, Icepak, Circuit, or Twin Builder API and workflow questions. Route setup, project inspection, runtime validation, image export, and session handling to ansysem-agent-bridge; never mutate AEDT or treat documentation as live proof."
---

# AnsysEM KB Docs

Use Runtime typed operations `docs.status`, `docs.query`, and `docs.get` as the
normal path. Documentation and generated indexes stay on the AEDT host and are
not redistributed by this Skill. The public `ansysem-agent docs` commands
remain setup and direct diagnostic interfaces.

For Bridge setup, project identity, live AEDT state, bounded execution, or
session lifetime, use `$ansysem-agent-bridge`. A pure documentation request
must not launch AEDT.

## Query

Submit a version-bound `docs.query` directly when the request already names
the API, symbol, or task. Use `docs.status` only for setup, missing-index, or
version ambiguity. The equivalent direct CLI is:

```text
ansysem-agent --pretty doctor
ansysem-agent --pretty docs status
ansysem-agent --pretty docs query "<exact symbol or task>" --module <module> --limit 6
```

Select an explicit installation when several are configured. Do not assume the
newest version. Treat each returned `source_ref`, module, source kind, and
validation status as evidence metadata.

If the bounded result is insufficient, expand one returned source:

```text
ansysem-agent --pretty docs get <source-ref> --focus "<symbol>" --max-chars 4000
```

Use at most three focused retrieval rounds. Do not scan the user's home
directory, open unrelated large manuals, reconstruct private paths, or copy
vendor documentation into a project or answer.

## Execution-route research

For an automation capability, prefer:

1. a public, version-matched PyAEDT or PyEDB API with a verified signature;
2. a documented native AEDT scripting operation when the Python abstraction is
   absent or loses required semantics;
3. bounded GUI assistance only after both API routes are shown inadequate.

A missing search result or one failed call is not proof that an API does not
exist. Identify wrong names, signatures, execution lanes, object-ID domains,
model prerequisites, and version differences before recommending a fallback.

## Evidence boundary

- Documentation evidence does not prove that the selected runtime exposes or
  successfully executes a symbol.
- A readable `.aedt` file does not prove that its `.aedb` bundle is complete.
- A visible port or geometry object does not prove electrical or solver-side
  correctness.
- Route live validation to `$ansysem-agent-bridge` and report the remaining
  gate explicitly.
