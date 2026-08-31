# AEDT supervised live-edit validation

The `0.2.0a12` candidate was exercised with AEDT 2026.1 and PyAEDT 1.4.0 on
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
- The a12 extension added one `2 mm x 1 mm` named rectangle on an existing `TOP`
  signal layer in the already-open graphical process. Object creation plus direct
  layout-property readback completed in about 937 ms of adapter time.
- Repeating the same patch ID returned `preserved` in about 12 ms and created no
  duplicate object. `rollback_patch` then checked the name/layer/net fingerprint,
  deleted only that rectangle through the Layout editor, and verified absence in
  about 204 ms.
- An initial truly empty acceptance fixture had no signal layer and AEDT correctly
  rejected rectangle creation. The fixture was given a `TOP` signal layer before
  the final acceptance; layer authoring is not part of this minimal live-edit API.
- Pi Agent independently exercised the same rectangle contract through Runtime
  only: create `run_3bb5b549a5934a7a9b395b5b7dc65d39`, idempotent replay
  `run_b8c5a09c2b804a52a51c5c20c39dbfbd`, and rollback
  `run_ddde230385174363af36c51726b75a63` all passed. It did not save or release
  the project implicitly; the disposable Runtime-owned session was explicitly
  released after acceptance.

## Safety boundary

Every operation reauthorizes the exact live identity. Existing-value edits check
the expected prior value; object creation checks that the requested name is
absent. A user-owned Context cannot claim Agent-owned release authority. Saving,
discarding, and patch rollback are explicit decisions; discard closes and reopens
the same project in the same graphical AEDT process.
