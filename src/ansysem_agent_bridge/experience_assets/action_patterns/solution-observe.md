---
schema_version: "eda.experience-asset/v1"
asset_version: "1.0.0"
id: "ansysem.hfss3dlayout.solution-observe"
kind: "action_pattern"
status: "validated"
summary: "Read an exact persisted HFSS 3D Layout solution without starting a solver, and return bounded pure-JSON numerical evidence."
intents: ["read existing simulation results", "recover after post-processing failure", "extract S Z L or Q curves without solving"]
tags: ["HFSS 3D Layout", "native program", "observe", "persisted results", "post-processing"]
applies_to: {"eda":"ansys-electronics-desktop","versions":["2026.1"],"profiles":["hfss3dlayout"],"os":["linux"]}
prerequisites: ["exact source project", "persisted results directory", "exact setup and sweep name", "explicit expression map"]
recommendation: "Before retrying an expensive solve, retrieve the exact existing solution with the attached observe-plan compiler; validate frequency grids, finite values, and optional magnitude bounds."
steps: ["copy the project bundle with persisted results", "list existing analysis sweeps", "require the exact solution", "read requested expressions", "normalise all values to JSON scalars", "return solver_started false"]
failure_signals: ["output exists after an apparently failed request", "solver completed but validation raised", "PyAEDT object is not JSON serialisable", "readback failure triggers an unnecessary re-solve"]
validation: {"method":"real AEDT 2026.1 persisted-result fresh readback plus pure-JSON compiler regression","recipe":"ansysem_agent_bridge.experience_recipes:compile_solution_observe_plan"}
official_refs: ["https://aedt.docs.pyansys.com/version/stable/API/visualization/_autosummary/ansys.aedt.core.visualization.post.post_common_3d.PostProcessor3D.get_solution_data.html"]
evidence_refs: ["docs/VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md", "docs/VALIDATION_2026-09-03_EXPERIENCE_RECIPES.md"]
confidence: 0.94
last_verified: "2026-09-03"
supersedes: []
---

# Recovery before replay

Solver execution and result extraction are different phases. A post-processing
exception, a missing local constant, or a non-JSON PyAEDT object does not prove
that AEDT failed to solve. If the intended output bundle or result directory
exists, observe it first and only resubmit analysis when persisted solution
evidence is genuinely absent or invalid.

The attached recipe compiles an `effect=observe` `native.execute`, sets
`include_results=true`, never writes the source, and reports
`solver_started=false`. The Agent still selects expressions, frequency grid,
passivity/convergence interpretation, and the customer-accuracy boundary.
