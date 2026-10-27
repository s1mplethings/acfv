# Trusted Speech Provenance

Trusted speech must retain Creator, Recording, time span, audio locator, raw ASR, confidence, re-decode agreement, model/config provenance, and profile version. A correction produced by Creator memory is not independent proof of itself. It remains untrusted until corroborated or human-confirmed. This prevents error → memory → repeated-error contamination.

Pseudo-trusted admission also requires compatible profile version, CONFIRMED or strict multi-source PROBABLE identity, clean overlap/music state, no critical ASR flags, high ASR confidence, local agreement, and independent evidence. Human review upgrades a unit only when both speaker and transcript are marked correct. Lexicon candidates and acoustic exemplars may be derived only from pseudo-trusted or human-confirmed units; incompatible prior-profile memory is preserved but excluded by default.

