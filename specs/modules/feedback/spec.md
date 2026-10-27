# Feedback and Explicit Preference Spec

## Purpose

Persist only reliable user signals: Clip acceptance/rejection, explicit boundary
changes, and preference text intentionally entered by the user.

## Inputs / Outputs

- Accept/Reject creates one Feedback snapshot from the current Clip boundaries.
- Boundary deltas are measured against the source Moment, not prior edits.
- ExplicitPreference stores optional Creator scope and `source=USER_EXPLICIT`.

## Retrieval Effect

No training or implicit inference is allowed. Retrieval applies transparent keyword
penalties for explicit avoid/don't preferences and small boosts for explicit
prefer/喜欢 preferences.

## Acceptance Criteria

- Clip, Feedback, and ExplicitPreference survive database reopen.
- Accept/Reject updates Clip review status through a service.
- A negative explicit preference can demote a matching candidate.
