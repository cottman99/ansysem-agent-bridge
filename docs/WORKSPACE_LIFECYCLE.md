# Candidate workspace lifecycle

## Purpose

An iterative EDA task should keep continuity without treating every correction
as a deliverable revision. The Bridge therefore separates a mutable candidate
workspace from an immutable promoted output.

```text
frozen source
     |
     v
candidate workspace -- typed patch --> internal checkpoint
     |                                  |       |
     |                                  + rollback
     + typed patch --> internal checkpoint
     |
     + explicit promote
             |
             + clean replay from frozen source --> immutable output
```

## State machine

| State/action | Durable effect | EDA verification | Permanent model version |
| --- | --- | --- | --- |
| `begin` | Locks source identity and creates generation 0 | Bundle check | No |
| `reconcile` | Applies one idempotent typed patch to a staged generation | Scoped fresh-reopen assertions | No |
| `rollback` | Selects the previous owned generation and truncates the journal | Bundle continuity check | No |
| `abort` | Removes owned generations and retains the audit manifest | None | No |
| `promote` | Replays the journal from the frozen source and commits a distinct output | Complete final assertion registry after fresh reopen | Yes |

The workspace revision is an optimistic-concurrency token, not a model version.
The caller must use the last returned value. A stable `patch_id` makes transport
retries idempotent: an identical patch returns `preserved`; reuse of the same ID
with different content is rejected.

Use a stable promotion ID. Repeating the exact output, ID, and retention policy
after a successful promotion returns `preserved` after digest verification and
does not launch EDA again. Abort is also safe to repeat.

## Performance and integrity

- Candidate continuity uses a compact state revision instead of rehashing every
  EDB file after every read-only status check.
- Bundle copies use copy-on-write reflinks when the host filesystem supports
  them and safely fall back to ordinary copies.
- Reconcile verifies only the assertions affected by that patch. Stable
  assertion IDs update the final registry instead of accumulating duplicates.
- Promote performs the expensive gate once: full frozen-source digest, clean
  replay, fresh-session final assertions, and full output digest.
- The candidate is never the source of a promoted delivery, so exploratory
  state cannot silently leak into the final model.

## Failure and recovery

The manifest is atomically replaced, flushed to stable storage where supported,
and guarded by a workspace lock. A failed
reconcile removes only its staged generation and leaves the last committed
revision usable. A stale same-host lock is recoverable when its process is gone;
abandoned staging directories and generations created before an interrupted
manifest commit are cleaned at the next stateful action. External
candidate drift, source drift, stale revisions, output overwrite, unregistered
operations, arbitrary Python, raw vendor calls, and solve requests are rejected.

Before the final replay starts, the manifest records a promotion intent with the
exact output, promotion ID, original workspace revision, retain policy, request
digest, and owned staging directory. If execution is interrupted, only that
exact request may resume. A complete output is freshly verified and committed
without replaying mutation; an incomplete owned output and its exact staging
directory are removed before one clean replay. This closes the power-loss window
between output commit and manifest commit without treating an attempt as a new
model version.

Retry an unchanged transport failure with the same `patch_id`. Correct a typed
precondition or assertion failure and submit a new patch ID. If the same semantic
failure repeats, stop and inspect the capability, target identity, and model
prerequisite before issuing more mutations.

## Scope

The lifecycle is generic; it does not add arbitrary AEDT access. A workspace can
only journal operations and assertions registered by its selected adapter. New
vendor behavior belongs in a reusable typed adapter capability, not in a
customer-specific command or Skill rule.
