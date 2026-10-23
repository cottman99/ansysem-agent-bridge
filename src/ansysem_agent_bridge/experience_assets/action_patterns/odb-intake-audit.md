---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.odb.intake-audit"
kind: "action_pattern"
status: "validated"
summary: "Inventory an ODB++ archive before importing it, and separate present electrical data from absent fabrication facts."
intents: ["inspect an ODB++ archive", "identify missing PCB fabrication inputs"]
tags: ["ODB++", "PCB", "intake", "static audit"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux","windows"]}
prerequisites: ["one unchanged ODB++ ZIP or TAR archive"]
recommendation: "Run the attached read-only inventory before AEDT import; treat missing stackup, plating, material, assembly, or component-value data as unknown rather than inferring it from nearby graphics."
steps: ["hash the archive", "inventory matrix layers", "inventory components and pin records", "compare EDA and CAD nets", "count through-drill features", "report missing or unproven fabrication facts"]
failure_signals: ["missing matrix", "empty signal-layer set", "missing net records", "component text mistaken for pad ownership"]
validation: {"method":"synthetic ZIP/TAR parser tests and sanitized project archive review","recipe":"ansysem_agent_bridge.experience_recipes:audit_odb_archive"}
official_refs: ["https://edb.docs.pyansys.com/version/stable/"]
evidence_refs: ["docs/VALIDATION_2026-09-03_EXPERIENCE_RECIPES.md"]
confidence: 0.78
last_verified: "2026-09-03"
supersedes: []
---

# Evidence boundary

ODB++ may contain board outline, copper, nets, component references, pin records,
and drill features while omitting the physical dielectric stackup, material
properties, plating, roughness, and actual assembly population. A successful
archive parse is therefore an intake result, not a simulation-ready model.

The attached recipe is deliberately static and read-only. It does not launch
AEDT, infer NC state, compare silkscreen proximity, or invent fabrication data.
It is not advertised as an EDA operation because the current governed AnsysEM
`native.execute` lane requires an existing AEDT project bundle.
