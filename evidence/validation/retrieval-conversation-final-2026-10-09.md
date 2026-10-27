# ACFV Retrieval Recall & Grounded Conversation Final Validation

## 1. Repository

- Branch: `fix/retrieval-conversation-final`
- Base: `d7aa5c6ee03a7f048900ad0ce98d6957f45bb4ec`
- Implementation: `6e8270f9e01cdff8114c91c7073c2b47f141255a`
- Commits: `104dac3`, `a13ea1e`, `6e8270f`
- Scope remained retrieval representation, grounded conversation, runtime visibility,
  evaluation tooling, tests, and corresponding specs. Frozen Capture/ASR/Moment/Clip
  implementation paths were not changed.

## 2. Retrieval Representation

- Product/result/evidence identity remains the parent Moment.
- FINAL Moments produce `SUMMARY`, `FULL_TRANSCRIPT`, bounded overlapping `PASSAGE`,
  and `NEIGHBOR_CONTEXT` representations. PROVISIONAL Moments retain the lighter path.
- Parent aggregation uses the best representation plus a bounded 2% second-hit bonus;
  representation count cannot linearly inflate a long Moment.
- The index manifest is version 4 and records model, dimension, backend, config hash,
  representation schema/config, parent count, and representation metadata.

## 3. Candidate Recall

- Dense Top-128 and FTS Top-128 are fused by parent Moment, then the best 50 parents
  are reranked. Results are parent-deduplicated.
- English question stopwords are removed before the FTS OR expression. This fixed the
  general candidate starvation observed in C03 without adding a case-specific rule.
- Diagnostics expose winning representation ID/type/excerpt, dense and FTS ranks,
  reranker score, final rank, token length, and truncation status.

## 4. Fixed Retrieval

| Metric | Baseline | V2 | V3 |
|---|---:|---:|---:|
| Top 1 | 0 | 11 | 11 |
| Top 3 | 0 | 12 | 14 |
| Top 5 | 0 | 13 | 15 |
| Top 10 | 0 | 14 | 17 |
| Top 30 | 0 | 14 | 18 |
| MRR | 0.0000 | 0.5854 | 0.6325 |
| Median latency | not recorded | 3262.5 ms | 1688.6 ms |
| P90 latency | not recorded | 3983.9 ms | 2088.4 ms |

The required Top-5 gate of 14/20 and target of 15/20 are both met.

## 5. Per Case R01–R20

| Case | V2 rank | V3 rank | Winning representation | Remaining failure |
|---|---:|---:|---|---|
| R01 | miss | 1 | SUMMARY | — |
| R02 | 1 | 1 | NEIGHBOR_CONTEXT | — |
| R03 | 1 | 1 | PASSAGE | — |
| R04 | 1 | 3 | PASSAGE | — |
| R05 | miss | miss | — | cross-language semantic abstraction before candidate cutoff |
| R06 | 8 | 6 | FULL_TRANSCRIPT | — |
| R07 | 1 | 3 | SUMMARY | — |
| R08 | miss | 1 | PASSAGE | — |
| R09 | 1 | 1 | NEIGHBOR_CONTEXT | — |
| R10 | 1 | 1 | PASSAGE | — |
| R11 | 3 | 4 | PASSAGE | — |
| R12 | 4 | 1 | PASSAGE | — |
| R13 | 1 | 1 | FULL_TRANSCRIPT | — |
| R14 | miss | miss | — | chat/subscription abstraction before candidate cutoff |
| R15 | 1 | 6 | NEIGHBOR_CONTEXT | — |
| R16 | 1 | 1 | PASSAGE | — |
| R17 | 1 | 15 | SUMMARY | relevant but reranker demotion |
| R18 | 1 | 1 | PASSAGE | — |
| R19 | miss | 3 | PASSAGE | — |
| R20 | miss | 1 | FULL_TRANSCRIPT | — |

## 6. Hard Retrieval Failures

| Case | Base parent dense rank | Base FTS parent rank | Tokens/truncated | V3 outcome | Diagnosis |
|---|---:|---:|---|---|---|
| R01 | 12 | — | 34 / no | rank 1 | multilingual E5 plus parent aggregation fixed recall |
| R05 | 2636 | — | 103 / no | miss | semantic paraphrase remains outside both candidate channels |
| R08 | 19 | — | 206 / no | rank 1 | passage representation fixed long/local evidence retrieval |
| R14 | 486 | — | 39 / no | miss | query describes chat behavior absent from searchable transcript wording |
| R19 | 3 | — | 215 / no | rank 3 | passage representation fixed rerank input locality |
| R20 | 42 | — | 80 / no | rank 1 | full transcript/parent fusion fixed candidate and final ordering |

No listed failure is caused by the 512-token model limit; all six target transcripts
fit without truncation.

## 7. Cross-language

- The controlled 2,000-background benchmark improved Top-5 from 9/20 with
  `multilingual-e5-small` to 14/20 with `multilingual-e5-base`; Top-10 improved
  11/20 to 16/20, median rank 8 to 1, and the three explicit cross-language probes
  remained 3/3.
- Full fixed-set V3 recovered R01, R08, R19, and R20. R05 and R14 remain documented
  misses rather than being hidden by query-specific aliases.

## 8. Conversation Runtime

- Provider: local Ollama 0.12.3; model: `qwen2.5:7b-instruct`.
- Runtime modes are explicit: `GROUNDED_LLM`, `EVIDENCE_ONLY`, and `DEGRADED`.
- The model receives only request-local IDs (`E1`, `E2`, …), parent evidence, and
  the winning retrieval excerpt. Returned IDs are validated, deduplicated, and
  mapped back to Moment/Recording/timestamps.
- Temperature is 0. A timeout or malformed payload receives one bounded repair,
  then falls back to `EVIDENCE_ONLY`.

## 9. Conversation Fixed Set

- Supported C01–C05: 5/5 grounded; C03 now answers `right trigger` with a valid
  citation to the correct Crow Country Moment.
- Multi-evidence C06–C10: 5/5 grounded; three cases cite multiple distinct evidence
  cards under the evaluator's coverage metric. C08 cites E1/E3/E4.
- No-evidence C11–C15: 5/5 rejected; invalid citations 0; unsupported claims 0.
- C11 allowed the LLM to inspect weak candidates but correctly returned no claim;
  C12–C15 were rejected by the pre-LLM sufficiency gate.

## 10. Conversation Performance

| Stage | Measurement |
|---|---:|
| Retrieval, median | 1688.6 ms |
| Retrieval, P90 | 2088.4 ms |
| Conversation overall, median | 5074.0 ms |
| C08 overall | 10504.6 ms |
| Reranker-only | not separately instrumented |
| LLM TTFT | not observable through the non-streaming JSON provider call |
| LLM total-only | not separately instrumented from overall conversation latency |

The report does not infer unmeasured stage timings.

## 11. Moment Regression

- 30 frozen Moment cases: punctuation-only 0; low-information suspects 0;
  `AUTO_SUSPECT` 2; summary-copy flags 10.
- The two suspect cases remain queued for human review. No Moment was rebuilt or
  rewritten for this pass.

## 12. Clip Regression

- 10 retained V2 media clips were copied without retranscoding and revalidated.
- ffprobe 10/10; mid-sentence starts 0; mid-sentence ends 0; rendered
  `AUTO_SUSPECT` 0; five bad retrieval sources were rejected as expected.
- Clip rendering and proposal code were not modified.

## 13. Live Regression

- `tests/e2e/test_live_product_e2e.py` passes in the full suite, covering capture
  replay, provisional search, finalization, clip, feedback, and restart.
- PROVISIONAL indexing remains lighter than FINAL indexing. The previously measured
  real Twitch time-to-first-searchable result was about 97 seconds; no new long
  replay was run because the frozen live path was unchanged.

## 14. Index

- Parents: 5,226; representations: 24,351 (SUMMARY 5,226; FULL_TRANSCRIPT 5,226;
  PASSAGE 8,673; NEIGHBOR_CONTEXT 5,226), average 4.659 representations/parent.
- Model: `intfloat/multilingual-e5-base`, 768 dimensions, real CPU backend.
- Full rebuild: 1777.474 s; RSS 94,486,528 → 2,211,168,256 bytes; persisted size
  182,864,929 bytes.
- An initial relative-path final write hit Windows `WinError 433`; the absolute-path
  retry succeeded and the issue/verification was recorded in Issue Memory.

## 15. Tests

- Two consecutive final-code pytest runs: 292 passed / 11 warnings, then
  292 passed / 11 warnings.
- Unified Windows verify: compile, CLI smoke, 292 tests, contract checks — PASS.
- Product + Live coverage: 86% (2,028 statements, 274 missed), above the 80% gate.
- Added regression coverage for passages, parent dedupe/bias, dense-rank-80 + FTS
  fusion, E5 prefixes/normalization, stable citations, malformed/timeout fallback,
  late evidence, winning excerpts, and lexical stopword filtering.

## 16. Bugs Fixed

| Severity | Problem | Fix | Evidence |
|---|---|---|---|
| P1 | Local facts disappeared in parent-long text | bounded passages + winning representation rerank text | R08/R19 recovered |
| P1 | Cross-language recall was weak | multilingual E5-base default and real-model index | R01/R20 recovered |
| P1 | Conversation could omit rank-6 evidence | default evidence window 5 → 8 | C03 candidate available |
| P1 | Conversation saw parent prefix, not winning neighbor/passage | include winning excerpt in gate and prompt | C03 grounded |
| P1 | FTS OR query was flooded by English question stopwords | stopword-filtered lexical terms | C03 target final rank 2 in direct audit |
| P2 | Invalid/malformed model output could leak ambiguity | stable E IDs, validation, one repair, truthful fallback | invalid citations 0 |
| P2 | Old index schema/model could be silently reused | v4 manifest compatibility and retrieval-only rebuild | runtime receipt |

## 17. Remaining Problems

- R05 and R14 remain candidate-recall misses. Both are semantic/observable-evidence
  mismatches, not truncation failures.
- R17 remains in Top-30 but drops to rank 15 after reranking.
- CPU index build uses about 2.21 GB RSS and takes about 29.6 minutes.
- Conversation median latency is about 5.07 seconds; C08 is about 10.50 seconds.
- Provider TTFT and reranker-only timing are not separately instrumented.
- Moment M07/M25-style review items remain human-review work; no automated product
  quality conclusion is asserted.

## 18. Evidence

- `evidence/product-evaluation-v3/metadata.json`
- `evidence/product-evaluation-v3/retrieval/raw_results/R01.json` through `R20.json`
- `evidence/product-evaluation-v3/retrieval/representation_diagnostics.json`
- `evidence/product-evaluation-v3/conversation/cases.json`
- `evidence/product-evaluation-v3/moments/cases.json`
- `evidence/product-evaluation-v3/clips/cases.json`
- `evidence/validation/retrieval-conversation-final-test-receipt.json`
- `evidence/validation/retrieval-conversation-runtime-receipt.json`
- `evidence/validation/retrieval-conversation-final-change-manifest.json`

## 19. External Reviewer Handoff

- Bundle: `evidence/product-evaluation-v3/evaluation_bundle_v3.zip`
- Size: 234,958,153 bytes.
- SHA-256: `ec27ae9cc5abd152982f21f8f1b1dc27daec454c9da8ce49a927ed3fb84242a0`.
- The bundle contains fixed-set raw results, diagnostics, holdout results, review
  sheets, and ten playable review clips. Human ratings remain `PENDING`; no human
  decision was fabricated.

## 20. Engineering Status

- Retrieval hard gate and target are met; grounded conversation safety gates pass;
  frozen Moment/Clip/Live regression checks pass.
- Code is committed locally in three reversible commits. No push, merge, tag, or PR
  mutation was performed.
- Rollback: `git revert 6e8270f a13ea1e 104dac3` (preferred), or reverse the final
  patch in dependency order. Generated V3 evidence can be removed independently.
- This is an engineering validation status only, not an MVP/product-quality verdict.
