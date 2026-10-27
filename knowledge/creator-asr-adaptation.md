# Creator ASR Adaptation

The first implementation uses the existing recognizer with Creator/Game hotwords on a bounded local audio window. A change needs re-decode evidence and independent trusted history. Speaker embeddings are excluded from lexical evidence. Total WER and high-risk identity, negation, number, game-term, and payoff accuracy must be evaluated per Creator on independent human truth before production enablement.

Generic decoding remains authoritative while adaptation is in Shadow. Creator resolution, profile-version compatibility, scoped trusted memory, and a bounded 30-term hotword set are mandatory. Missing profile, empty trusted context, identity conflict, version mismatch, or adaptive decoder failure all return the Generic result. Shadow comparisons cannot self-promote into trusted memory. Production is a per-Creator human decision supported by blind A/B review and independent transcripts; it is never auto-enabled.

