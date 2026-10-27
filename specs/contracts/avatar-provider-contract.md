# Avatar Provider Contract

`identify_frame(frame, timestamp_ms)` returns visual observations only. Providers cannot write Library/domain state or generate transcripts. Model-specific preprocessing and labels stay behind the adapter.

Selection requires an explicit model path, executable entrypoint, and versioned external-label mapping. Discovery is bounded and filename-only candidates are never activated. Unknown labels must remain persisted observations with `candidate_creator_id = null`; they must not create Creators. Frame observations require temporal aggregation before becoming visual spans, and even a strong span proves only visual presence—not active speech.

