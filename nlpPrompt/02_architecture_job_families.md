You are a principal product architect, senior NLP systems designer, and B2B SaaS strategist.

Your task is to transform the project “NLPFInalVersion” from a mostly technical-role AI recruiter into a multi-department AI Hiring Intelligence Platform that can support hiring across an entire company.

The current system already supports:
- CV parsing
- technical skill extraction
- candidate-job matching
- interview generation/evaluation
- reports/explainability

But it is still too focused on technical hiring.

Your mission:
Redesign the product architecture so it can support multiple job families professionally, without becoming a messy pile of hard-coded skills.

====================================================
CORE ARCHITECTURAL PRINCIPLE
====================================================

Do NOT simply add hundreds of new skills into one global catalog.

Instead, redesign the system around:

1. Job Family
2. Skill Taxonomy per Job Family
3. Scoring Policy per Job Family
4. Evidence Rules per Job Family
5. Interview Template per Job Family

The target system should become:

“A family-aware AI Hiring Platform that can evaluate candidates differently depending on whether the role is engineering, marketing, accounting, HR, operations, sales, support, design, or admin.”

====================================================
TARGET JOB FAMILIES
====================================================

Phase 1 families:
1. engineering
2. marketing
3. finance_accounting
4. hr
5. operations

Phase 2 families:
6. sales
7. customer_support
8. design
9. logistics
10. general_admin

====================================================
WHAT EACH JOB FAMILY MUST DEFINE
====================================================

For every job family, design:

A. Skill Taxonomy
Examples:
- engineering:
  languages, frameworks, cloud, databases, devops
- marketing:
  SEO, SEM, Google Ads, Meta Ads, GA4, copywriting, campaign management
- finance_accounting:
  Excel, reconciliation, accounts payable, accounts receivable, payroll, QuickBooks, IFRS
- hr:
  recruitment, onboarding, employee relations, HRIS, performance management
- operations:
  inventory, procurement, logistics, vendor management, process improvement, ERP

B. Evidence Types
Examples:
- engineering:
  projects, code tools, frameworks
- marketing:
  campaign metrics, ROAS, CTR, budgets, portfolio
- finance_accounting:
  certifications, reconciliations, ERP tools, month-end close
- hr:
  hiring volume, policy work, employee cases
- operations:
  SLA improvement, throughput, cost reduction, vendor/process work

C. Scoring Policy
Each family must define:
- hard skill weight
- soft skill weight
- domain knowledge weight
- years/experience weight
- project/portfolio/KPI evidence weight
- certifications/licenses weight where relevant

D. Interview Templates
Each family must define:
- question categories
- what skills are tested
- scenario/case questions
- rubric style

====================================================
MANDATORY SYSTEM EXPANSION
====================================================

1. Add Job Family Classification
Design:
- how a job is assigned a family
- rule-based first pass
- optional LLM assist
- recruiter override
- persistence in DB

2. Expand Candidate Profile
The profile must support:
- skills
- tools
- certifications
- licenses
- industries
- achievements
- KPIs
- projects / portfolio
- management experience
- languages
- domain evidence
- soft skills

3. Generalize Evidence Extraction
The system must extract evidence beyond technical projects:
- project evidence
- campaign evidence
- KPI evidence
- certification evidence
- portfolio evidence
- tool evidence
- leadership evidence
- process improvement evidence

4. Generalize Matching
Refactor matching so it:
- loads job family
- selects the correct taxonomy
- selects the correct scoring policy
- uses family-specific evidence rules
- still supports shared/common skills
- remains explainable and grounded

5. Generalize Interview Generation
Interview questions must depend on:
- job family
- seniority
- matched/missing competencies
- available evidence
- role-specific templates

6. Generalize Reports
Reports must explain:
- why candidate fits this specific job family
- which family-specific competencies matched
- what evidence supports each claim
- what gaps matter for this family

7. Preserve Existing Engineering Behavior
The current technical hiring system must continue to work.
The redesign must be additive and backward-compatible.

====================================================
REPOSITORY REVIEW REQUIREMENTS
====================================================

Before proposing architecture, inspect:
- backend/app/api
- backend/app/services
- backend/app/models
- backend/app/schemas
- backend/alembic
- frontend/src
- current skill catalog
- current matching engine
- current interview generation
- current reports/explainability

Identify:
- what is currently engineering-specific
- what can be reused
- what must be generalized
- what should remain shared/global

====================================================
REQUIRED OUTPUT FORMAT
====================================================

A. Current Limitation Diagnosis
Explain exactly why the current system is too engineering-focused.

B. Target Product Definition
Define the new product as a multi-department AI Hiring Intelligence Platform.

C. Target Architecture
Show:
- shared/global layer
- job-family layer
- taxonomy layer
- scoring-policy layer
- evidence layer
- interview-template layer

D. Job Family Design Table
Job Family | Skill Groups | Evidence Types | Scoring Priorities | Interview Focus

Include at least:
- engineering
- marketing
- finance_accounting
- hr
- operations
- sales
- customer_support
- design
- logistics
- general_admin

E. Data Model Changes
Propose exact new fields/entities, such as:
- Job.family
- Candidate.tools
- Candidate.certifications
- Candidate.licenses
- Candidate.achievements
- Candidate.kpis
- Candidate.industries
- SkillEvidence
- JobFamilyProfile
- ScoringPolicy
- InterviewTemplate
- Competency

For each:
- fields
- relationships
- indexes
- migration priority

F. Backend Refactor Plan
List exact services likely to change:
- skill_catalog
- cv_parser
- enhanced_cv_parser
- job_parser
- matching / hybrid_matcher
- interview
- enhanced_interview
- explainability
- report generation

For each:
- what is currently hard-coded
- what should become family-aware
- minimal safe refactor path

G. Frontend Product Expansion
Describe new screens and workflows:
- family-aware job creation
- candidate evidence profile
- family-specific reports
- shortlist workflow
- dashboard filters by department/family

H. NLP Plan
Explain:
- family classification
- family-specific extraction
- taxonomy normalization
- evidence extraction
- grounded reporting
- multilingual considerations

I. Implementation Roadmap
Break into phases:

Phase 1:
- architecture foundation
- Job.family
- policy/taxonomy abstraction
- preserve engineering behavior

Phase 2:
- add marketing, finance_accounting, hr, operations

Phase 3:
- add family-specific interviews and reports

Phase 4:
- add sales, support, design, logistics, admin

J. Acceptance Criteria
For each phase define exact behaviors and tests.

K. Risks
List:
- over-generalization risk
- false skill extraction risk
- taxonomy explosion
- score inconsistency
- migration risk
- UI complexity

L. Final Recommendation
Answer:
- what to build first
- what to postpone
- how to avoid turning the system into an unmaintainable giant catalog

====================================================
RULES
====================================================

- Be specific, not generic.
- Do not hand-wave.
- Tie recommendations to the existing codebase.
- Use exact file paths where possible.
- Preserve backward compatibility with current engineering matching.
- Prefer abstractions only when they solve a real scaling problem.
- The final design must make future job families easy to add without rewriting the system again.