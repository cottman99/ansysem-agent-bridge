# Visual assets

`readme/logo.png`, `readme/ansysem-engineer-workflow-v3.png`, and
`readme/social-preview.png` are synthetic assets generated with OpenAI Image 2.
They contain no customer model, simulation result, proprietary vendor data,
private host information, EDA screenshot, or vendor artwork.

`readme/ansys-native-s-parameters.png` is an AEDT application-window capture
of the persisted native Report from the synthetic public workflow acceptance;
it is not a Python replot. It contains no customer design or private path. Its
evidence boundary is documented in
`VALIDATION_2026-08-30_HFSS3DLAYOUT_WORKFLOW.md`.

`readme/ansys-native-layout-stackup.png` is a real AEDT application-window
capture from a separate post-acceptance replay of the same public typed build
contract. It shows the project and design tree, layout, edge ports, and the
TOP / SUB / GND stackup. The replay was kept outside workflow timing and did
not run a solve; it contains no customer model or private path.

The product overview depicts the maintained stackup/geometry/port to solve and
native-report path. It is not itself proof that a specific AEDT operation or
solve ran; maintained capability claims and acceptance evidence remain in the
repository documents.

`readme/supervised-live-edit-latency.png` is the shared exact-data presentation
of the bounded 2026-08-31 ADS and AEDT supervised live-edit acceptances. The
AEDT panel is sourced from `VALIDATION_2026-08-31_LIVE_EDIT.md`; warm edits are
live-call time, while create, replay, and rollback are adapter time. The two
vendor panels use different timing boundaries and are not a vendor ranking.
