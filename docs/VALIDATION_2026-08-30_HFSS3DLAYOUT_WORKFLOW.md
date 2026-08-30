# HFSS 3D Layout build-to-report acceptance — 2026-08-30

This is a sanitized, synthetic workflow acceptance for the public Bridge. It
proves that the maintained typed operations can build and persist a small HFSS
3D Layout design, run an explicit sweep, read finite result data, export CSV,
create a native AEDT report, and find the same evidence after a fresh reopen.
It is not an RF accuracy reference or a customer-design benchmark.

## Tested environment

| Item | Value |
| --- | --- |
| EDA worker | Linux, remote Runtime connection |
| AEDT | 2026.1 |
| PyAEDT | 1.4.0 |
| PyEDB | 0.82.0 |
| Display | `:4.0` |
| Design | Synthetic two-port microstrip-like acceptance fixture |

## End-to-end result

| Stage | Result | Elapsed time | Durable evidence |
| --- | --- | ---: | --- |
| Create empty project | Passed | 36.83 s | Freshly reopenable HFSS 3D Layout bundle |
| Build stackup and layout | Passed | 40.05 s | 3 layers, ground rectangle, signal trace, `P1`/`P2`, `Setup1` |
| Solve explicit sweep | Passed | 122.27 s | Five finite points, two expressions, CSV, native `S Parameters` report, results directory |
| Export live editor image | Passed | 22.15 s | Native AEDT top-view PNG |
| Total Bridge adapter time | Passed | 221.30 s | Source bundles preserved throughout |

The build transaction closed PyEDB, reopened the staged EDB, converted it to a
matching AEDT project, closed AEDT, and then reopened the saved project in a
fresh AEDT session. Both fresh readers found the expected ports and setup.

The solve transaction created a discrete `Sweep1` from 1 GHz through 5 GHz in
1 GHz steps, blocked until analysis completed, exported the requested
expressions, created the native report, closed AEDT, and freshly reopened the
solved project. The fresh session found the report, sweep, results directory,
and all five finite frequency points.

## Exact sanitized data

The exported evidence is stored as
[`hfss3dlayout-microstrip-sparameters.csv`](benchmarks/hfss3dlayout-microstrip-sparameters.csv).
The columns are the AEDT CSV export for `dB(S(P1,P1))` and `dB(S(P2,P1))` at
1, 2, 3, 4, and 5 GHz. These numbers demonstrate numeric transport and
persistence only; they are not presented as a tuned transmission-line result.

The native editor evidence is stored as
[`hfss3dlayout-microstrip-real.png`](assets/hfss3dlayout-microstrip-real.png).
The image proves only that AEDT exported the named editor state. It does not
replace object, port, setup, sweep, or solution assertions.

## Run identities

| Operation | Runtime run ID |
| --- | --- |
| Project create | `run_eb3fe21955a14a839a7dc4a255fd2938` |
| Layout build | `run_1a620be40ef44256b1e2da561439533f` |
| Layout solve | `run_9126c3f97fe1442ca4872bd89cca2be3` |
| Image export | `run_5c241f9c087c4272a31a96c12fec2c85` |

## README model-window replay

The informative README model-window capture was made in a separate
post-acceptance replay of the same typed public build contract. This kept
release preparation outside the workflow timing above and avoided treating a
screenshot task as engineering execution time. The replay did not solve:

| Operation | Runtime run ID |
| --- | --- |
| Project create | `run_aac1d0d6f3a740969101ea4f0f0e883c` |
| Layout build | `run_791c2ee3ac8a4e32af2a8ee67bacf1f0` |
| Open owned AEDT window | `run_d24715739e8647bb9fc4b5dd1e7a4299` |

The source was preserved, the fresh-reopen build assertions passed, and the
window was framed to show the project/design tree, layout, edge ports, and
TOP / SUB / GND stackup. The resulting asset is
[`ansys-native-layout-stackup.png`](assets/readme/ansys-native-layout-stackup.png).

## Boundaries discovered and fixed

- PyEDB 0.82 rejected the attempted `Mitered` trace-corner token; the typed
  adapter now uses its supported `Sharp` corner form.
- AEDT and EDB must share a basename during conversion. Staging now preserves
  that invariant instead of creating loosely related files.
- A copied stale `.aedt` can overwrite newer EDB state. The transaction now
  opens the staged EDB and saves a matching AEDT project before fresh reopen.
- An adaptive setup alone did not prove the requested frequency coverage. The
  solve contract now creates an explicit named discrete sweep and requires a
  minimum persisted point count.
- Numeric acceptance validates every real and imaginary result value, not one
  scalar or a report-name-only proxy.
- The final build acceptance used negative XY coordinates, proving that the
  geometry contract does not assume an all-positive drawing quadrant.
- The final candidate used rollback-safe multi-entry commit: EDB, results, and
  exports move first, while the `.aedt` file becomes visible last as the bundle
  commit marker. Synthetic fault injection proves earlier moves are restored if
  that final rename fails.

AEDT `ValidateDesign` returned a PyAEDT gRPC error in this environment, so the
build gate does not misreport it as geometry validation. Persisted geometry and
identity checks remain in `layout.build`; explicit analysis and result checks
remain in `layout.solve`.
