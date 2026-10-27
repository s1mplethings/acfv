# Capability Dependency Graph

```text
Twitch Capture -> Creator Library -> Live Processing -> Processing Pipeline -> Moment Lifecycle
  -> Retrieval -> Grounded Conversation -> Clip Rendering -> Clip Review -> Feedback
```

GUI and CLI are adapters. Product services may depend on LibraryRepository and the
existing backend, pipeline, provider, step, and runtime infrastructure. Forbidden new
directions are UI → database session, conversation → FFmpeg, retrieval → rendering,
feedback → UI, and library → UI.
