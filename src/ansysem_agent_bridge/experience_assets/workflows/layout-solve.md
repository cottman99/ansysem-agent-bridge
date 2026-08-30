---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.hfss3dlayout.solve-and-validate"
kind: "workflow"
status: "validated"
summary: "Run a bounded HFSS 3D Layout solve job and validate expected native result artifacts without overwriting the source."
intents: ["solve an accepted HFSS 3D Layout project", "produce validated result artifacts"]
tags: ["HFSS 3D Layout", "solver", "artifacts", "job"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"],"capabilities":["layout.solve"]}
prerequisites: ["accepted source project", "named setup", "license availability", "explicit solve authorization"]
recommendation: "Use only when the named setup and artifact assertions match; retain the durable job receipt and never infer success from process exit alone."
steps: ["verify source and setup", "copy to staging", "submit solve", "wait durably", "validate artifacts and source preservation", "promote output"]
failure_signals: ["license or setup unavailable", "solver timeout", "missing or stale result artifact"]
validation: {"method":"durable solver job plus artifact validation","evidence":"docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md"}
official_refs: ["https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.hfss3dlayout.Hfss3dLayout.analyze.html"]
evidence_refs: ["docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md"]
confidence: 0.88
last_verified: "2026-08-30"
supersedes: []
---

# Evidence boundary

This is an accepted solver lifecycle shortcut. Solver types, setup families,
and post-processing outside its contract remain reachable through documented
governed native execution.
