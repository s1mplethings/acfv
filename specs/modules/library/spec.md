# Creator Library Spec

## Purpose

Persist the single-user product state above the existing ACFV processing engine. Creator, Source, and Recording are long-lived product objects; pipeline artifacts remain the media-processing source of truth.

## Inputs

- Creator display name and optional avatar URL.
- Twitch channel identity or another future source identity.
- Local recording path, source URL, timestamps, content type, and analysis profile.
- Existing ACFV configuration when processing is requested.

## Outputs

- SQLite state at `var/acfv.db` by default.
- Stable Creator, Source, and Recording IDs across restarts.
- Artifact locators pointing to canonical pipeline run directories.

## Process

1. Bootstrap versioned SQLModel tables without deleting an existing database.
2. Create or update a Creator independently from its platform Sources.
3. Register a Recording and keep recording, processing, and indexing states separate.
4. Delegate processing to `acfv.backend.service`; the Library never performs ASR itself.
5. Recover stale RECORDING/PROCESSING/INDEXING states to retryable failures on startup.
6. Bind an existing stream-monitor target to a Source and translate recorder events into
   durable Recording state without making the recorder depend on the Library database.
7. A completed real capture starts the existing backend processing job; LibraryService
   observes its canonical artifacts and persists terminal state.

## Data Contract

- Creator: id, display_name, slug, optional avatar_url, timestamps.
- Source: creator_id, platform, source_type, external_id, channel identity, enabled, metadata JSON.
- Recording: creator/source identity, source/local paths, timing, three lifecycle states, content profile, artifact locator, file fingerprint, timestamps.
- LibraryFolder: optional local-folder ingestion configuration.

## Configuration

- `ACFV_STORAGE_ROOT` overrides the writable storage root.
- Default database: `<storage_root>/acfv.db`.

## Error Handling

- Duplicate creator slugs, source identities, and canonical recording paths resolve to existing rows.
- Missing local files are rejected for manual imports, but live capture may reserve a Recording before the file exists.
- Interrupted lifecycle states become retryable failures at bootstrap.
- Unknown monitor targets and unrelated presence events are ignored; a bound source that
  has been removed is reported as an integration error.

## Acceptance Criteria

- Creator, Source, and Recording survive service disposal and database reopen.
- Creator and Source are independent objects.
- Recording status dimensions can change independently.
- GUI and CLI use LibraryService; neither writes SQL directly.
- Existing pipeline artifacts are referenced, not copied into SQLite.
- Twitch live detection can drive RECORDING to COMPLETE (or FAILED) through monitor events.
- The primary GUI can add a Twitch Creator, inspect Recording state/detail, retry
  processing, and rebuild the shared Moment index through services only.
