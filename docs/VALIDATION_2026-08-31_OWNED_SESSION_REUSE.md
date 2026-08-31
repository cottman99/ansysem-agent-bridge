# AEDT 2026.1 owned-session reuse and lifecycle timing

The `0.2.0a10` candidate was tested on Linux virtual display 4 with AEDT
2026.1 and PyAEDT 1.4.0. The acceptance used one disposable empty HFSS 3D
Layout project, did not open customer data, and did not solve.

## Result

| Path | Client transport | Bridge adapter | AEDT connect/open | Readback | AEDT release |
| --- | ---: | ---: | ---: | ---: | ---: |
| Cold live snapshot | 23.063 s | 22.805 s | 14.664 s | 27.9 ms | 7.929 s |
| Owned-session reuse, persistent transport | 1.125 s | 762.1 ms | 552.8 ms | 27.2 ms | none |
| Owned-session reuse, first call after transport reset | 2.047 s | 818.2 ms | 557.4 ms | 27.6 ms | none |

The persistent-transport adapter path improved by about 29.9 times. The
engineering readback itself was about 28 ms in both cases. In the cold path,
AEDT launch/project open consumed about 64% of adapter time and desktop release
about 35%; Runtime and persistent SSH were not the dominant cost.

Launching the owned session took 15.645 s and its final verified release took
6.156 s. Reuse therefore helps when several operations share one deliberate
engineering session; it is not useful for a single isolated read.

## Safety gates

- Reuse requires the exact opaque resource id and handle returned by
  `session.launch`.
- The Bridge resolves the private port and verifies active ownership, project,
  AEDT version, design, and process id before readback.
- A missing handle, stale process, changed identity, or another project fails
  closed. The Bridge never attaches to an arbitrary visible AEDT process.
- Reused readback does not close AEDT. The separate idempotent
  `session.release` operation closed the exact owned process after the test.
- Phase timings are returned in the operation receipt so later performance
  analysis does not require reconstructing the run from Agent chat history.
