You are a senior backend engineer specializing in production AI/NLP systems.

Your task is to implement the approved architecture plan for “NLPFInalVersion” directly in the repository.

You must work like a careful senior engineer:
- inspect before editing
- preserve existing working behavior
- make minimal but complete changes
- add tests with every risky change
- keep compatibility with the current system
- finish the work end-to-end, not only partially

====================================================
PRIMARY OBJECTIVE
====================================================

Implement all roadmap items below in a production-safe way.

====================================================
MUST BEFORE SELLING
====================================================

1. Production AI reliability
- In production, real embeddings must be required
- Do not silently downgrade to hash embeddings in production
- Add explicit degraded/failure handling when AI providers are unavailable
- Persist provider/model/version metadata on match/report outputs where appropriate

2. Ollama production readiness
- Add model bootstrap/pull support
- Add Ollama healthcheck
- Ensure API readiness depends on required models being available
- Cover parsing, interview, and embedding models

3. Readiness checks
- Extend readiness endpoint to verify:
  - DB connectivity
  - Redis availability
  - LLM provider reachability
  - embedding provider reachability
- Update Docker healthchecks to use readiness

4. Reliable queue behavior
- Disable in-memory CV task fallback in production
- If Redis is unavailable in production, fail clearly instead of risking task loss
- Add robust task status/error behavior

5. Official data migration/backfill
- Create an idempotent script/service to:
  - normalize old skills
  - repair aliases/typos
  - re-extract missing CV skills from raw_text
  - rebuild embeddings
  - invalidate stale MatchResult and Report rows
- Add logging and safe re-run behavior

6. Golden NLP benchmark
- Add fixture dataset and automated benchmark tests covering:
  - extraction
  - normalization
  - matching
  - report consistency
  - known regressions

7. Privacy basics
- Ensure complete candidate deletion:
  - candidate row
  - CV file
  - embeddings
  - reports
  - match results
  - interview sessions
- Add retention-policy support if missing
- Verify PII access boundaries

8. Full E2E tests
- Implement backend E2E coverage:
  CV upload → candidate persisted → embeddings created
  job create → match
  interview create → answer submit → evaluation
  report generation → persisted consistency

====================================================
MUST BEFORE ENTERPRISE
====================================================

1. Add scoring versioning
- scoring_version in MatchResult and Report
- ensure future algorithm changes remain explainable

2. Add full audit trail
- skill source:
  - extracted
  - raw text
  - project evidence
  - synonym
  - ESCO
- model/provider/version metadata
- explain score changes

3. Add monitoring hooks
- structured counters/logs for:
  - LLM failure
  - embedding failure
  - queue failure
  - zero-similarity
  - parse failure
  - report failure

4. Add/load test scaffolding
- scripts or tests for:
  - bulk CV upload
  - matching at scale
  - concurrent interview workload

5. Add backup/restore documentation and scripts if missing

6. Harden security
- review file upload validation
- secrets handling
- trusted hosts
- CORS
- rate limiting
- PII deletion

7. Add admin observability backend support
- expose provider status
- model availability
- queue status
- degraded state
- embedding freshness
- migration status

8. Add deployment docs/runbooks

====================================================
NICE LATER
====================================================

Only implement if they fit cleanly after the critical roadmap:
- richer report explanations
- comparison improvements
- branded exports
- better RAG
- additional ESCO enrichment
- voice improvements
- future feedback loop foundations

====================================================
MANDATORY IMPLEMENTATION RULES
====================================================

1. Start by reading the approved architecture plan and current repo state.
2. Before changing code, produce a concise implementation checklist.
3. Make the changes in logical batches.
4. For every batch:
   - update code
   - update tests
   - run relevant tests
5. Prefer existing project conventions and helpers.
6. Do not invent parallel architectures if the current code can be extended safely.
7. Do not break API compatibility unless absolutely necessary.
8. For DB changes:
   - add Alembic migrations
   - keep them reversible when feasible
   - document any data backfill
9. For Docker/runtime changes:
   - update compose files
   - update env examples
   - make startup behavior deterministic
10. For observability:
   - use structured logs/metrics-friendly fields
11. For privacy:
   - verify actual deletion paths, not just UI behavior
12. If a requested feature is too large to finish safely in one pass:
   - implement the correct foundation
   - clearly document the remaining exact work

====================================================
EXPECTED DELIVERABLES
====================================================

1. Code changes
2. New migrations
3. New scripts/services where needed
4. Updated Docker/runtime files
5. Updated env examples
6. New tests
7. A concise changelog of what was implemented
8. Verification commands and results

====================================================
FINAL RESPONSE FORMAT
====================================================

A. Implemented
- feature
- files changed
- behavior added

B. Migrations / Backfill
- what changed
- how to run
- what gets recomputed

C. Verification
- exact commands run
- exact results

D. Remaining Work
- only if something is not fully complete
- exact reason
- exact next files/functions to modify

E. Risks
- anything that still deserves caution before release

====================================================
QUALITY BAR
====================================================

The final result must be something another senior engineer would accept in review:
- no fake completion
- no silent regressions
- no shallow placeholders
- no untested critical logic
- no production setting that quietly gives low-quality NLP outputs