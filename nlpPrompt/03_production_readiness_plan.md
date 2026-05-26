You are a principal software architect, technical program manager, and AI product readiness lead.

Your job is to design a professional upgrade plan for the project “NLPFInalVersion” so it becomes ready for:
1. paid pilot customers,
2. serious technical companies,
3. later enterprise expansion.

You must act like the orchestration layer for a full engineering team:
- backend architecture
- NLP/ML reliability
- DevOps/runtime
- security/privacy
- QA/testing
- observability
- migration strategy
- product readiness

Do NOT start coding yet.
First, inspect the repository end-to-end and produce a complete implementation blueprint.

====================================================
PROJECT GOAL
====================================================

The system is an AI Recruiter Assistant with:
- CV upload/parsing
- skill extraction and normalization
- embeddings and vector matching
- candidate-job matching/ranking
- interviews and answer evaluation
- reports/explainability
- RAG
- voice
- authentication
- Docker deployment

The system must be upgraded with the following roadmap.

====================================================
MUST BEFORE SELLING
====================================================

1. Production AI reliability
- Real embeddings in production only
- No silent fallback to hash embeddings in production
- Explicit degraded state when AI providers fail
- Provider/model/version metadata saved with matches/reports

2. Ollama production readiness
- Automatic model bootstrap/pull
- Ollama healthcheck
- API must not start as “ready” before required models are available
- Confirm required models for parsing, interviews, and embeddings

3. Real readiness checks
- Readiness endpoint must verify:
  - database
  - Redis
  - Ollama / LLM provider
  - embedding provider
- Docker healthchecks must use readiness, not a shallow liveness endpoint

4. Reliable CV task queue
- No in-memory queue fallback in production
- No silent task loss on restart
- Proper degraded/failure behavior if Redis is unavailable
- Clear task failure states and retry strategy

5. Official data migration/backfill
- Normalize legacy skills
- Fix old aliases/typos
- Re-extract missing skills from old CV raw text
- Rebuild candidate/job embeddings
- Invalidate stale MatchResult and Report rows
- Must be safe, idempotent, and auditable

6. Golden NLP benchmark dataset
- CV fixtures
- job fixtures
- expected extracted skills
- expected matched skills
- expected score/rank ranges
- regression checks for known edge cases

7. Privacy basics
- Candidate data deletion
- CV file deletion
- retention policy support
- access-control review for PII
- clear ownership of stored personal data

8. Full end-to-end tests
- CV upload → candidate persistence → embeddings
- create job → matching
- interview creation → answer submission → evaluation
- report generation
- DB and API consistency assertions

====================================================
MUST BEFORE ENTERPRISE
====================================================

1. Scoring/versioning
- scoring_version on matches/reports
- versioned formulas and weights
- historical results remain explainable after algorithm changes

2. Full audit trail
- source of every matched skill:
  - CV extracted skill
  - raw text evidence
  - project evidence
  - synonym/alias
  - ESCO mapping
- provider/model/version for NLP outputs
- explanation of why a score changed

3. Monitoring and alerts
- embedding failures
- LLM failures
- zero-similarity spikes
- queue backlog
- parsing failure rate
- report generation failures

4. Load/performance validation
- large candidate sets
- concurrent CV uploads
- concurrent interviews
- matching latency
- vector search performance

5. Backup and restore strategy

6. Strong production security review
- secret management
- HTTPS assumptions
- file upload hardening
- rate limits
- PII handling
- least privilege
- secure defaults

7. Admin observability
- current AI provider status
- model availability
- queue health
- degraded-mode status
- embedding freshness
- migration/backfill status

8. Deployment docs and recovery runbooks
- install
- configure
- upgrade
- backup
- restore
- provider outage
- Redis outage
- DB migration rollback

====================================================
NICE LATER
====================================================

1. Better UI polish
2. More explanation text and charts
3. More languages and dialects
4. Better interview analytics
5. Recruiter feedback loop for ranking
6. Candidate comparison improvements
7. Exportable/branded PDF reports
8. More ESCO enrichment
9. Better RAG
10. Voice improvements

====================================================
MANDATORY WORKFLOW
====================================================

1. Inspect the current repository structure.
2. Build a dependency map:
   - APIs
   - services
   - models
   - DB tables
   - async/background workers
   - external providers
   - Docker/runtime components
3. Compare current implementation against every requested feature above.
4. Identify:
   - what already exists
   - what is partial
   - what is missing
   - what must be refactored before new work
5. Design the target architecture.
6. Break implementation into phases with minimal risk.
7. Define ownership boundaries by module.
8. Define required migrations, new tables/columns, services, endpoints, config flags, background jobs, and test suites.
9. Call out compatibility risks with the current codebase.
10. Produce a final engineering plan that another senior engineer can implement directly.

====================================================
OUTPUT FORMAT
====================================================

A. Current State Summary
- What already exists
- What is production-ready
- What is partial
- What is missing

B. Target Architecture
- New services/modules
- Modified services/modules
- New DB fields/tables
- New runtime dependencies
- New configuration variables
- New observability hooks

C. Feature-by-Feature Gap Table
Feature | Current State | Required Change | Priority | Risk | Dependencies

D. Proposed Implementation Phases
Phase 0: prerequisites
Phase 1: Must before selling
Phase 2: Must before enterprise
Phase 3: Nice later

For each phase include:
- exact files likely to change
- new files likely to be added
- migrations required
- API changes
- test changes
- rollout risk

E. Data Migration Strategy
- exact backfill logic
- idempotency strategy
- rollback strategy
- what gets invalidated and recomputed

F. Production Readiness Checklist
- what must be true before pilot sale
- what must be true before enterprise sale

G. Acceptance Criteria
- concrete technical checks proving each feature is complete

H. Recommended Implementation Order
- exact order of execution
- reasons for that order

====================================================
RULES
====================================================

- Do not hand-wave.
- Use exact file paths and functions when describing current code.
- If something is unknown, say “Unknown” and list exactly what to inspect next.
- Prefer minimal changes that fit the existing architecture.
- Do not propose unnecessary rewrites.
- Keep backward compatibility in mind.
- Treat NLP correctness, auditability, and production reliability as first-class concerns.