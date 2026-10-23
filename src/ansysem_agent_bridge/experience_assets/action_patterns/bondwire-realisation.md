---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.hfss3dlayout.bondwire-realisation"
kind: "action_pattern"
status: "validated"
summary: "Compile explicit bondwire endpoints and APD profiles, then verify the realised 3D shape instead of trusting names or direction flags."
intents: ["create or correct bondwires", "verify reverse BSOB shape", "audit bondwire length and clearance"]
tags: ["HFSS 3D Layout", "PyEDB", "bondwire", "APD", "BSOB", "3D geometry"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"]}
prerequisites: ["exact wire identities", "Agent-confirmed physical endpoints", "Agent-confirmed loop profiles and expected apex endpoint"]
recommendation: "Use the attached compiler after endpoint and loop intent are fixed; require projected length, apex endpoint, conductor landing, obstacle, and pairwise-clearance assertions on the reopened model."
steps: ["declare APD profiles", "declare expected-before and desired wire state", "batch the mutation", "reconstruct reopened 3D polylines", "verify physical apex endpoint, length, landings, and clearances"]
failure_signals: ["wire name says reverse but shape is forward", "endpoint swap and reverse profile cancel", "projected length outside tolerance", "wire crosses dielectric or another wire"]
validation: {"method":"real AEDT/PyEDB 2026.1 typed bondwire transaction plus physical-polyline assertions","recipe":"ansysem_agent_bridge.experience_recipes:compile_bondwire_plan"}
official_refs: ["https://edb.docs.pyansys.com/version/stable/"]
evidence_refs: ["docs/VALIDATION_AEDT_2026R1_LINUX.md", "docs/VALIDATION_2026-09-03_EXPERIENCE_RECIPES.md"]
confidence: 0.92
last_verified: "2026-09-03"
supersedes: []
---

# Physical meaning

`start`, `end`, profile `direction`, and process-language labels are separate
facts. Swapping endpoints while also reversing the profile can produce the same
physical rise as an ordinary wire. The attached recipe therefore requires an
explicit expected apex endpoint and emits a `bondwire_apex_endpoint` assertion.
The adapter derives it from the reopened 3D polyline: which landing has the
near-vertical rise/descent to the loop apex.

Loop-class selection, customer height rules, pad mapping, and obstacle identity
remain Agent/project-contract decisions. The recipe does not guess them.
