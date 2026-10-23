---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.hfss3dlayout.gap-port-reference"
kind: "action_pattern"
status: "validated"
summary: "Compile an explicit HFSS 3D Layout terminal map into local-reference Gap ports and fresh-reopen assertions."
intents: ["create lumped ports", "correct port reference geometry", "audit local port references"]
tags: ["HFSS 3D Layout", "Gap port", "lumped port", "reference conductor"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"]}
prerequisites: ["exact project identity", "Agent-confirmed signal object and side", "Agent-confirmed reference layer, net, depth, and continuity"]
recommendation: "Use the attached compiler only after engineering intent has produced an explicit terminal map; validate actual port type, properties, reference tokens, and common-reference continuity after reopening."
steps: ["confirm signal and reference terminals", "compile one batch of create_gap_port operations", "save and close", "freshly reopen", "read port type, reference, impedance, renormalisation, and de-embedding"]
failure_signals: ["Circuit instead of Gap type", "reference patch stops before common ground", "wrong selected side", "port count passes while reference geometry is wrong"]
validation: {"method":"real AEDT 2026.1 typed gap-port transaction plus compiler regression","recipe":"ansysem_agent_bridge.experience_recipes:compile_gap_port_plan"}
official_refs: ["https://aedt.docs.pyansys.com/version/stable/API/_autosummary/ansys.aedt.core.hfss3dlayout.Hfss3dLayout.create_edge_port.html"]
evidence_refs: ["docs/VALIDATION_AEDT_2026R1_LINUX.md", "docs/VALIDATION_2026-09-03_EXPERIENCE_RECIPES.md"]
confidence: 0.93
last_verified: "2026-09-03"
supersedes: []
---

# Use the terminal map, not a port-name heuristic

The Agent must decide which object is the signal terminal, which local conductor
is the reference, and whether the intended direction is horizontal or vertical.
The recipe only compiles those decisions into the existing `model.apply`
contract. It creates no new operation and does not constrain other official
PyAEDT or native port APIs.

The decisive evidence is the fresh-reopen port property and reference readback.
Counting ports or viewing a marker is insufficient. If a temporary reference
patch is required, its depth and common-ground continuity belong in the project
contract and independent geometry/net assertions.
