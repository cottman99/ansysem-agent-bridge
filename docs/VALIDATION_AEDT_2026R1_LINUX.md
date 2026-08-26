# AEDT 2026 R1 Linux acceptance

Date: 2026-08-26
Release candidate: `0.1.0a1`
Environment: Linux, AEDT 2026.1.0, PyAEDT 1.4.0, Python 3.11

## Public-safe result

The wheel was deployed into an isolated directory on an AEDT host and tested
against a private, complete HFSS 3D Layout project bundle on the operator's
selected graphical virtual display. No solve was requested or run.

| Gate | Result | Evidence retained publicly |
| --- | --- | --- |
| Wheel import and CLI launch | Passed | Versioned package and local build/test gates |
| Exact project bundle inspection | Passed | Complete `.aedt` plus `.aedb/edb.def`; identity omitted |
| Live AEDT launch and project/design readback | Passed | Non-empty release, process, project, design, editor, setup, and port state |
| Native `ZoomToFit` and `ExportImage` | Passed | Non-empty artifact with SHA-256; private image deleted after visual inspection |
| Owned-session cleanup | Passed | Every process created by the acceptance commands was absent afterward |
| `ValidateDesign` through PyAEDT | Attention required | PyAEDT 1.4.0 raised a gRPC API error for this project |

The `ValidateDesign` branch produced a useful product correction: the Bridge
now captures identity and readback before optional validation, preserves that
evidence if validation raises, and reports `attention_required` instead of
collapsing the entire snapshot into an opaque error.

## Privacy boundary

The public repository contains no acceptance project, screenshot, raw AEDT
log, host address, user path, project/design name, customer identifier,
credential, license detail, or vendor documentation. Temporary private image
copies were deleted after hash and visual checks.

## Claim boundary

This acceptance supports the live identity, compact readback, native image
export, and safe lifecycle claims for the tested release. It does not support
claims about electrical correctness, mesh generation, convergence, numerical
results, or unimplemented editing and solve operations.
