# AEDT 2026 R1 Linux acceptance

Date: 2026-08-27
Release candidates: `0.1.0a1` for read/export, `0.1.0a2` for native typed
transactions, `0.1.0a3` for typed bondwire transactions, and `0.2.0a1` for
resumable candidate workspaces; `0.2.0a5` revalidates Runtime-driven candidate
abort and rollback dispatch
Environment: Linux, AEDT 2026.1.0, PyAEDT 1.4.0, PyEDB 0.82.0, Python 3.11

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

## Typed bondwire acceptance (`0.1.0a3`)

A disposable private-project copy exercised `hfss3dlayout.pyedb-native/v1`
with synthetic operation and profile names. It compiled one structured APD
profile, changed one exact-name wire without moving its endpoints, saved and
closed PyEDB and AEDT, then passed nine assertions after fresh AEDT and PyEDB
reopens. The source fingerprint and full source bundle remained unchanged; the
temporary plan, result, and output were removed after inspection.

| Gate | Result |
| --- | --- |
| Expected `.aedt` and `edb.def` fingerprints | Passed |
| Structured APD profile; no raw parameter block | Passed |
| Exact-name wire and `expected_before` precondition | Passed |
| Type, profile, diameter, material, endpoints, and projected length readback | Passed |
| Fresh AEDT design/display/port/setup and clean geometry check | Passed |
| Fresh PyEDB wire count, profile height, and persisted properties | Passed |
| Source unchanged, output complete, no solve or packaging | Passed |

## Privacy boundary

The public repository contains no acceptance project, screenshot, raw AEDT
log, host address, user path, project/design name, customer identifier,
credential, license detail, or vendor documentation. Temporary private image
copies were deleted after hash and visual checks.

## Candidate workspace acceptance (`0.2.0a1`)

A private disposable source copy exercised the public
`aedt.transaction_workspace` lifecycle with the PyEDB-native adapter. No task
specific name, coordinate, project path, raw log, or model was retained in the
public repository.

| Gate | Result |
| --- | --- |
| Wheel, required Skill, runtime profile, and display | Passed |
| Begin from frozen source | Passed; generation 0 used a filesystem reflink |
| Typed reconcile and fresh reopen | Passed; 4/4 scoped assertions |
| Identical patch replay | `preserved` in about 1 second; no EDA call |
| Internal rollback | Passed in about 1 second; returned to generation 0 without an external model version |
| Reconcile after rollback | Passed; 4/4 scoped assertions and pure JSON stdout |
| Explicit promotion | Passed; clean replay from the frozen source, 4/4 final assertions, complete output |
| Identical promotion replay | `preserved` in about 0.1 seconds after digest verification; no EDA call |
| Integrity | Source unchanged; source and output full-bundle SHA-256 digests recorded |
| Cleanup | Candidate generations removed after promotion; all owned AEDT and EDB processes exited |
| Solve, packaging, publication, or release action | Not requested or run |

Synthetic power-loss tests additionally interrupt promotion both before output
creation and after a complete output commit but before manifest commit. The
first path removes only the intent-owned partial output and staging directory
before replay; the second performs fresh-reopen verification without reapplying
mutation. A normal failed promotion returns the same candidate workspace to
`draft` with a new optimistic revision.

The live run exposed and corrected one general interface defect: PyEDB progress
messages could contaminate the CLI standard output and force callers to scrape a
mixed stream. Vendor diagnostics now go to standard error; standard output is
exactly one JSON document and was parsed directly during the second reconcile
and promotion.

On this AEDT 2026.1 / PyEDB 0.82 environment, the final wheel's actual reconcile
and promotion took about 46 and 45 seconds respectively. Candidate cloning
itself used reflinks; the dominant remaining cost was owned AEDT/PyEDB
save-close-fresh-reopen work plus PyEDB's fallback from unavailable
shared-memory IPC to standard gRPC.

## Runtime candidate-abort regression acceptance (`0.2.0a5`)

A public-safe greenfield case created an empty HFSS 3D Layout source, began one
candidate workspace, carried the returned optimistic revision into abort, and
freshly inspected the frozen source. The same case ran independently through
Codex and a dedicated Pi Agent profile on `DISPLAY=:4.0`.

The first run exposed a general Runtime-adapter defect: `workspace.abort` and
the adjacent `workspace.rollback` dispatch passed a keyword-only revision as a
positional argument. Both Agents supplied the correct observed revision, both
received the same typed failure, and neither claimed success. The adapter now
forwards `expected_workspace_revision` explicitly; regression tests cover both
operations.

After installing the candidate wheel into the isolated remote environment,
both fresh Agent runs passed all four Runtime calls. Each verified a complete
unchanged source Bundle, an aborted workspace with its candidate removed, no
promoted output, and no solve. All owned scratch and processes were checked and
removed. The public evidence retains no paths, project files, Agent trace, job
identity, or customer data.

## Claim boundary

This acceptance supports the live identity, compact readback, native image
export, narrow typed property/gap-port and bondwire transactions, persistence,
resumable candidate workspaces, clean-replay promotion, and safe lifecycle
claims for the tested release. It does not support claims
about arbitrary editing, electrical correctness, mesh generation, convergence,
numerical results, or solve operations.
