# AEDT 2026 R1 Linux acceptance

Date: 2026-08-26
Release candidates: `0.1.0a1` for read/export and `0.1.0a2` for typed transactions
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

## Typed transaction acceptance (`0.1.0a2`)

A second private disposable-copy acceptance exercised the public runtime
profile and `hfss3dlayout.native/v1` transaction rather than a project-specific
script. It created two semantic outer-edge gap ports with typed reference
patches, changed three exact native properties, saved and closed the owned AEDT
session, and verified twelve assertions after a separate fresh reopen.

| Gate | Result |
| --- | --- |
| Exact profile Python, display, module, and library environment | Passed |
| Refuse source overwrite and stage a complete bundle | Passed |
| Registered operations only; no arbitrary Python or command | Passed |
| Two gap ports and three exact property mutations | Passed |
| Save, owned-session close, and separate fresh reopen | Passed |
| Design, display, port count/names, setup, net, type, and reference assertions | 12/12 passed |
| Source full-bundle hashes unchanged and output bundle complete | Passed |
| Solve, packaging, publication, or release action | Not requested or run |
| Transaction staging, output copy, plan, and raw result cleanup | Passed |

The live gate found and corrected two runtime-profile defects before promotion:
loader-path changes must exist before Python starts, and a virtual-environment
Python entry point must not be normalized through its symbolic link. The Bridge
now performs a controlled re-execution of its own fixed CLI under the exact
profile interpreter and pre-launch environment; it still exposes no arbitrary
command field.

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
export, narrow typed property/gap-port transaction, persistence, and safe
lifecycle claims for the tested release. It does not support claims about
arbitrary editing, electrical correctness, mesh generation, convergence,
numerical results, or solve operations.
