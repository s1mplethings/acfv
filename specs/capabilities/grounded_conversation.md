# Grounded Conversation

- Purpose: answer only when retrieved Moment evidence supports a claim.
- Canonical Interface: `acfv.conversation.service.GroundedConversationService`.
- Implementation: `src/acfv/conversation/`.
- Inputs: question, retrieval scope, result limit.
- Outputs: short answer with validated `E1`-style citations and cited
  `SearchResult` evidence cards.
- Effects: optional call to the existing LLM client after evidence sufficiency checks.
- Errors: unsupported or invalid citations return the no-evidence response;
  provider timeout/malformed output falls back to evidence-only after one repair.
- Dependencies: Retrieval only; never FFmpeg or database sessions.
- Acceptance: No Evidence → No Claim, and the LLM is not called without evidence.
  Cross-language evidence without lexical overlap is admitted only with a strong
  reranker signal or a high dense score in the top three; weak matches stay rejected.
