# AEDT supervised live-edit validation

The `0.2.0a11` candidate was exercised with AEDT 2026.1 and PyAEDT 1.4.0 on
Linux virtual display 4. The acceptance used a disposable empty HFSS 3D Layout
project, did not open customer data, and did not solve.

## Result

- Both Codex and Pi Agent used only the copied live project/design Context to
  create a design variable in the already-open graphical AEDT process, read it
  back, and explicitly discard the unsaved project state.
- A second run in the same process repeated the sequence with a different value;
  the PyAEDT connection was cached only for the exact process, port, project,
  version, and design identity.
- Warm live-edit calls completed in about 296-453 ms. No new AEDT process or
  project copy was created for each patch.
- A separate lifecycle regression confirmed that a refused validated session
  launch releases the Runtime-owned AEDT process instead of leaking it.

## Safety boundary

Every operation reauthorizes the exact live identity and checks the expected
prior value before mutation. A user-owned Context cannot claim Agent-owned
discard authority. Saving or discarding requires an explicit decision; discard
closes and reopens the same project in the same graphical AEDT process.
