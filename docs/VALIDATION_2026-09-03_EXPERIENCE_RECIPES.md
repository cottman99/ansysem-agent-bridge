# Experience-owned engineering recipes — 2026-09-03

## Purpose

This acceptance adds four engineering experiences without adding a Router,
semantic gate, public operation id, or alternative AEDT API. A recipe is
returned only after `experience.get` selects its exact asset id. It compiles
already-decided data into an existing `model.apply` or `native.batch` contract,
or performs a bounded static archive read.

No customer names, paths, geometry, connectivity, or material values are
packaged in the Bridge.

## Result

| Experience | Status | Acceptance |
| --- | --- | --- |
| ODB++ intake audit | Validated | Synthetic ZIP regression plus one private archive: ZIP, 64 members, 4 signal layers, 0 dielectric layers, 31 top components, 19 matching EDA/CAD nets, and 284 through-drill features; missing dielectric stackup reported rather than inferred |
| Gap-port reference plan | Validated | Compiler produces only registered `create_gap_port` operations and fresh-reopen property/reference assertions; the underlying typed port path had already passed real AEDT 2026.1 acceptance |
| Bondwire realisation plan | Validated | A real AEDT/PyEDB 2026.1 transaction rebuilt the frozen v018 BSOB correction into an isolated candidate; fresh-reopen assertions read the realised polylines and confirmed the expected physical apex endpoint for W01, W11, and W18 |
| Persisted-solution observation | Validated | Real private AEDT 2026.1 observe run read 11 finite points from DC through 5 GHz, reported `solver_started=false`, included existing results by reflink, and preserved the source bundle |

## Persisted-solution live acceptance

The accepted read used the stable AnsysEM Runtime connection and the public
`native.batch` operation with `effect=observe`. The recipe required one exact
setup/sweep and one S-parameter expression. It did not invoke `analyze`, create
an output, or write an artifact.

| Item | Result |
| --- | --- |
| Run | `run_c8289e76dd1c44bb886a2004151b7724` |
| Job | `job_e34ae99457b4446db7b0f77cfca4c3d0` |
| Runtime state | Passed |
| Adapter time | 27.525 s |
| Copy | 5 control files, reflink, persisted results included |
| Frequency grid | 11 points, 0–5 GHz |
| Solver started | False |
| Source preserved | True |

The first two dispatch attempts were rejected before EDA execution: one because
two AnsysEM connections required an exact connection id, and one because the
generic Runtime classifies `native.batch` conservatively and therefore requires
an idempotency key even when the enclosed plan is observe-only. These are
transport/authorization facts, not solver failures. The accepted third request
used the exact connection and stable idempotency key.

## Bondwire live acceptance

The candidate Bridge replayed the frozen v018 BSOB correction from its preserved
v017 source into a new isolated output. It created two APD profiles, updated the
three intended wires, and then reopened the result before evaluating assertions.

| Item | Result |
| --- | --- |
| Run | `run_4eb477111f104a9db95048d86e186fdb` |
| Job | `job_66a888733d1a4fd5895624ac1e1e96bf` |
| Runtime state | Passed |
| Adapter time | 45.403 s |
| Bondwire population | 17 |
| Realised apex endpoint | W01=start, W11=start, W18=start |
| Other checks | Projected length, conductor landings, obstacle clearance, pairwise clearance, and geometry clean all passed |
| Solver started | False |

The first acceptance attempts exposed configuration, not modelling, defects:
the payload initially omitted the required `plan` wrapper, and the candidate
profile initially relaunched through the stable Bridge package. The candidate
connection now keeps stable AEDT dependencies while prepending only the candidate
Bridge package. The stable connection and source/official projects were unchanged.

## Regression

The complete repository suite passed after the implementation:

```text
153 passed
ruff: all checks passed
```

The tests cover:

- experience-library hashes and exact compiled-shortcut lookup;
- recipe invisibility in ordinary operation selection;
- recipe return only after exact asset selection;
- ODB++ signal/dielectric/component/net/drill separation;
- explicit Gap-port settings and reference tokens;
- endpoint-order preservation and realised apex-endpoint checks;
- no-solve persisted-result plan generation and JSON-safe output.

## Claim boundary

This acceptance supports the four packaged experience recipes and the exact
tests above. It does not claim general ODB++ import, automatic connectivity or
loop-profile inference, customer-accuracy simulation, or complete HFSS 3D
Layout feature coverage. It validates the stated explicit-endpoint workflow, not
automatic inference of process direction, customer pad mapping, or loop class.
