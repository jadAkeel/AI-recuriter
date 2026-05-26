You are a senior AI product architect, SaaS product strategist, and full-stack technical lead.

Your task is to transform the project “NLPFInalVersion” from a limited AI recruiting demo into a sellable AI Hiring Copilot product for technical companies.

You must think like:
- a CTO
- a product manager
- a senior full-stack architect
- an NLP/AI systems reviewer
- a B2B SaaS founder

Do NOT start coding immediately.
First inspect the repository, understand what already exists, then design a professional expansion plan and implementation roadmap.

====================================================
CORE CONCERN
====================================================

The current product has good foundations:
- CV parsing
- skill extraction
- matching
- interviews
- reports
- some explainability

But it feels too small and too limited to sell as a serious B2B product.

Your mission:
Turn it into a larger, coherent, sellable platform.

The product should answer this business question:

“How can a company select the right candidate faster, with confidence, and with evidence?”

====================================================
TARGET PRODUCT VISION
====================================================

Build toward:

AI Recruiter Assistant Pro / AI Hiring Copilot

A platform that helps technical hiring teams:
- ingest many CVs
- understand candidate evidence
- match candidates to jobs
- shortlist candidates
- manage pipeline stages
- conduct AI-assisted interviews
- evaluate answers
- compare candidates
- generate hiring recommendations
- export/share reports
- track decisions and audit history
- customize scoring policies and skill taxonomy

====================================================
MUST EXPAND PRODUCT AREAS
====================================================

1. Candidate Pipeline
Add or design:
- candidate stages:
  - New
  - Parsed
  - Matched
  - Shortlisted
  - Interview
  - Reviewed
  - Offer
  - Rejected
- stage history
- recruiter notes
- candidate tags
- decision status
- rejection/shortlist reasons
- assigned recruiter
- last activity timestamp

Goal:
Recruiters should manage candidates as a workflow, not just as rows.

2. Job Intelligence
Add or design:
- job description quality analysis
- seniority detection validation
- required vs optional skills cleanup
- ambiguous requirement warnings
- suggested missing skills
- suggested interview plan
- job readiness score
- job calibration summary

Goal:
The system should help companies write better job requirements before matching.

3. Candidate Evidence Profile
Add or design:
For each candidate, show structured evidence:
- extracted skills
- source of each skill:
  - CV skill section
  - experience
  - project
  - education
  - raw text
  - LLM
  - ESCO/catalog
  - synonym/alias
- confidence
- evidence snippet
- positive/negative/learning status
- project evidence
- experience evidence
- weak/uncertain skills

Goal:
Every user-visible claim must be traceable to evidence.

4. Smart Shortlisting
Add or design:
- shortlist generation per job
- shortlist explanation
- hard filters vs soft ranking
- “why selected”
- “why not selected”
- missing critical skills
- project-based upside for juniors
- overqualified warnings
- rank movement after interview
- shortlist approval workflow

Goal:
Recruiters should get a decision-ready shortlist, not only a score table.

5. Interview Suite
Add or design:
- interview kit per job
- skill-based questions
- project-based questions
- seniority-based questions
- custom question bank
- interviewer notes
- AI answer evaluation
- evidence-backed interview summary
- post-interview score adjustment
- consistency between interview result and final report

Goal:
Interviews should be part of the hiring workflow, not a separate feature.

6. Company Dashboard
Add or design:
- open jobs overview
- candidates processed
- best matches
- shortlist counts
- interview status
- average match score
- skill gaps across applicants
- bottlenecks by stage
- recent activity
- AI health/degraded status

Goal:
The company should understand its hiring pipeline at a glance.

7. Professional Reports
Add or design:
- candidate report
- job report
- shortlist report
- interview report
- comparison report
- final hiring recommendation
- PDF/export-ready report structure
- report sharing permissions
- report versioning

Goal:
Reports should be boardroom/client-ready, not just debug output.

8. Admin / Enterprise Layer
Add or design:
- company/workspace model
- teams/departments
- users and roles
- scoring policies
- custom skill taxonomy
- custom interview templates
- audit logs
- data retention settings
- privacy controls
- provider configuration visibility
- degraded-mode visibility

Goal:
The system should feel like a real SaaS platform, not a single-user tool.

9. Analytics and Feedback Loop
Add or design:
- recruiter feedback on match quality
- accepted/rejected reasons
- calibration over time
- skill demand analytics
- candidate source analytics
- score distribution
- false positive/false negative tracking
- future learning loop foundation

Goal:
The product should improve and provide business intelligence.

10. Integrations / Future Surface
Design but do not overbuild:
- ATS import/export
- LinkedIn/manual candidate import
- calendar integration
- email invitations
- Slack/Teams notifications
- webhook events
- CSV export/import
- PDF report export

Goal:
Prepare the architecture for real company workflows.

====================================================
NON-NEGOTIABLE PRODUCT PRINCIPLES
====================================================

1. Evidence-first
No claim about a candidate should appear without traceable source evidence.

2. Recruiter workflow-first
The app should support a real hiring process from job creation to final decision.

3. Human-in-the-loop
AI suggests; recruiters approve, reject, override, and leave reasons.

4. Configurable but not chaotic
Companies can adjust scoring policies and taxonomies without breaking consistency.

5. Production-ready foundation
Any new product feature must fit with:
- real embeddings
- provider health
- readiness checks
- queue reliability
- privacy
- auditability
- versioning

6. Minimal rewrite
Prefer extending the existing architecture over rebuilding everything.

====================================================
MANDATORY REPOSITORY REVIEW
====================================================

Before proposing changes, inspect:
- backend/app/api
- backend/app/services
- backend/app/models
- backend/app/schemas
- backend/alembic
- frontend/src/pages
- frontend/src/components
- frontend/src/types
- Docker/runtime files

Build a current product map:
- current features
- current entities
- current user flows
- missing product workflows
- reusable modules
- risky modules
- data model gaps

====================================================
OUTPUT FORMAT
====================================================

A. Product Diagnosis
Explain:
- why the current system feels too small
- what is strong
- what is missing
- what blocks it from being sellable as a B2B SaaS

B. Target Product Definition
Define the expanded product in one clear paragraph.

C. New Product Modules
For each module:
- purpose
- user value
- backend changes
- frontend changes
- DB/model changes
- NLP/AI changes
- risks
- MVP version
- later version

Modules must include:
- Candidate Pipeline
- Job Intelligence
- Evidence Profile
- Smart Shortlisting
- Interview Suite
- Company Dashboard
- Professional Reports
- Admin/Enterprise Layer
- Analytics/Feedback Loop
- Integrations/Future Surface

D. Data Model Expansion
Propose exact entities/fields, such as:
- Company / Workspace
- CandidateStage
- CandidateStageHistory
- CandidateNote
- CandidateTag
- SkillEvidence
- JobAnalysis
- Shortlist
- ShortlistItem
- ScoringPolicy
- AuditLog
- ReportVersion
- RecruiterFeedback
- InterviewTemplate
- InterviewQuestionBank

For each:
- fields
- relationships
- indexes
- migration priority

E. Backend Architecture Plan
List:
- new endpoints
- modified endpoints
- new services
- modified services
- background jobs
- migrations
- validation rules

F. Frontend Architecture Plan
List:
- new pages
- modified pages
- new components
- state/API changes
- dashboard changes
- recruiter workflows

G. NLP/AI Architecture Plan
Explain how to support:
- skill evidence provenance
- project evidence
- job quality analysis
- shortlist reasoning
- interview question planning
- report grounding
- feedback loop

H. Product Roadmap
Break into milestones:

Milestone 1 — Sellable MVP Expansion
Must include:
- Candidate pipeline
- Evidence profile
- Smart shortlist
- Job intelligence basic
- Better reports

Milestone 2 — Paid Pilot Readiness
Must include:
- reliability foundation
- benchmark
- privacy basics
- E2E tests
- admin health

Milestone 3 — Technical Company Product
Must include:
- scoring policies
- audit logs
- report versions
- analytics dashboard
- interview templates

Milestone 4 — Enterprise Expansion
Must include:
- workspaces/teams
- retention policies
- integrations
- advanced monitoring
- backup/restore
- runbooks

I. Implementation Order
Give the exact safest order:
1. DB foundation
2. backend services
3. API
4. frontend flows
5. tests
6. migration/backfill
7. release gate

J. Acceptance Criteria
For every milestone, define:
- what must work
- what tests must pass
- what demo should prove
- what business question it answers

K. Risk Register
List:
- technical risks
- NLP correctness risks
- product risks
- scope creep risks
- migration risks
- UI complexity risks

L. Final Recommendation
Answer:
- what should be built first
- what should be delayed
- what not to build yet
- what makes the product sellable fastest

====================================================
RULES
====================================================

- Be specific.
- Do not give generic SaaS advice.
- Tie every recommendation to the existing project.
- Use exact file paths where possible.
- If unknown, say “Unknown” and specify where to inspect.
- Prefer a coherent product over random feature expansion.
- Keep the first sellable version realistic.
- Do not overbuild enterprise features before the product has a strong MVP workflow.