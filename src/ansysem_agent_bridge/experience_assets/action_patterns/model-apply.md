---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.model.apply-transaction"
kind: "action_pattern"
status: "validated"
summary: "Apply a bounded registered model plan to a staged AEDT project and accept it only after fresh-reopen assertions."
intents: ["modify an existing AEDT model", "apply several known model edits safely"]
tags: ["PyAEDT", "PyEDB", "staging", "fresh-reopen"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"],"capabilities":["model.apply"]}
prerequisites: ["exact source project and design", "source bundle fingerprint", "complete structured plan and assertions"]
recommendation: "Use this compiled shortcut only when its registered plan vocabulary exactly matches the already-decided edits; otherwise generate a governed official native batch."
steps: ["verify source fingerprint", "copy to staging", "apply registered operations", "save and close", "fresh reopen and assert", "promote new output"]
failure_signals: ["unregistered operation", "source fingerprint mismatch", "fresh-reopen assertion failure"]
validation: {"method":"fresh-reopen assertions and source preservation","evidence":"docs/VALIDATION_AEDT_2026R1_LINUX.md"}
official_refs: ["https://aedt.docs.pyansys.com/version/stable/"]
evidence_refs: ["docs/VALIDATION_AEDT_2026R1_LINUX.md"]
confidence: 0.9
last_verified: "2026-08-30"
supersedes: []
---

# Evidence boundary

This asset describes the maintained transaction shortcut, not every model edit
available in AEDT. Missing operations belong in governed official native
execution rather than an ever-growing operation vocabulary.
