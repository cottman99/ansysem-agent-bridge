---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.hfss3dlayout.build"
kind: "workflow"
status: "validated"
summary: "Create a bounded HFSS 3D Layout project through official PyAEDT and verify the saved project after reopening."
intents: ["build a new HFSS 3D Layout model", "create a reproducible layout fixture"]
tags: ["HFSS 3D Layout", "PyAEDT", "project-build"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"],"capabilities":["layout.build"]}
prerequisites: ["non-existing output target", "complete versioned build plan", "available AEDT 2026.1 profile"]
recommendation: "Use the compiled workflow for its accepted build schema; use governed native execution for geometry or setup fields outside that schema."
steps: ["validate plan", "build in staging", "save and close", "fresh reopen", "verify design and objects", "promote output"]
failure_signals: ["output already exists", "unsupported plan field", "fresh-reopen mismatch"]
validation: {"method":"real AEDT build and fresh-reopen readback","evidence":"docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md"}
official_refs: ["https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.hfss3dlayout.Hfss3dLayout.html"]
evidence_refs: ["docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md"]
confidence: 0.9
last_verified: "2026-08-30"
supersedes: []
---

# Evidence boundary

The accepted schema is a fast path for one project-build family. It is not the
complete PyAEDT object model and does not constrain generic official API reach.
