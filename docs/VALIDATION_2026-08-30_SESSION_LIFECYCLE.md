# AEDT 2026.1 interactive-session lifecycle acceptance

The `0.2.0a7` candidate was installed in the isolated AnsysEM environment on `eda-server` and
tested with `DISPLAY=:4.0`. The test created a disposable empty HFSS 3D Layout project; it did not
open a customer project and did not solve.

- Capability discovery advertised separate mutating `session.launch` and `session.release`
  operations. Read-only `runtime.snapshot` rejects requests that try to leave a new process open.
- `session.launch` opened a new AEDT 2026.1 desktop and returned an
  `eda-runtime.resource/v1` resource marked `runtime-owned` with a reusable opaque release handle.
- `session.release` matched the stored resource, gRPC port, and live process id before closing the
  desktop. The exact test process was absent afterward.
- An initial candidate named the opaque field `release_token`; Runtime correctly redacted it, which
  made it unusable for the return call. The contract was corrected to `release_handle` and the full
  launch-release acceptance was repeated successfully.
- Unit coverage also rejects an invalid handle, refuses a changed process identity, and verifies an
  already released resource idempotently. No force-kill path exists in the public operation.
