# AI Recruiter Assistant — PROJECT MAP

## TECH STACK
- Backend: FastAPI + SQLAlchemy (async), PostgreSQL (prod), SQLite (dev)
- AI: sentence-transformers (local), OpenAI optional, pgvector
- Frontend: static HTML + JS
- Infra: Docker + docker-compose

## SYSTEM ARCHITECTURE
- Backend API Layer: REST API (FastAPI)
- AI Layer: CV parsing, job understanding, embeddings, matching, interview, explainability
- Data Layer: PostgreSQL + pgvector, optional Redis
- Frontend Layer: Recruiter UI (web)

## FULL DATA FLOW
1. CV upload
2. CV parsing
3. Embedding generation
4. Job parsing
5. Matching + ranking
6. Interview session
7. Evaluation
8. Explainable report

## AI PIPELINE FLOW
1. CV Intelligence Engine
2. Job Understanding Engine
3. Embedding & Matching System
4. LLM Interview Agent
5. Explainability Layer

## MODULE BREAKDOWN
- docker-compose.yml: local stack
- backend/Dockerfile: API container
- .dockerignore: Docker ignore rules
- backend/.dockerignore: backend ignore rules
- backend/app/main.py: API bootstrap and routing
- backend/app/core/config.py: configuration
- backend/app/core/logging.py: async logging
- backend/app/core/db.py: database connection
- app/api/cv.py: CV parsing endpoint
- app/services/cv_parser.py: CV parsing logic
- app/schemas/candidate.py: parsed CV schema
- app/services/embedding.py: embedding generation
- app/services/vector_store.py: vector database access
- app/models/embedding.py: embeddings table
- app/services/job_parser.py: job understanding logic
- app/services/matching.py: candidate-job ranking
- app/api/jobs.py: job endpoints
- app/api/candidates.py: candidate endpoints
- app/api/matching.py: matching endpoint
- app/api/interviews.py: interview endpoints
- app/api/reports.py: report endpoints
- app/models/candidate.py: candidate storage
- app/models/job.py: job storage
- app/models/match_result.py: match storage
- app/models/interview.py: interview sessions
- app/models/report.py: report storage
- app/services/skill_catalog.py: shared skill taxonomy
- app/services/interview.py: interview engine
- app/services/explainability.py: report generator
- frontend/index.html: recruiter UI
- frontend/app.js: frontend logic
- frontend/styles.css: styling

## COMPLETED
- Backend core setup (DONE, verified)
- CV parsing system (DONE, verified)
- Embedding + vector DB integration (DONE, verified)
- Matching engine (DONE, verified)
- AI interview system (DONE, verified)
- Evaluation + explainability layer (DONE, verified)
- Frontend integration (DONE, verified)
- End-to-end verification (DONE, verified)

## DATABASE DESIGN (HIGH LEVEL)
- Candidates, Jobs, Applications, Interviews, Evaluations, Reports
- Embeddings stored in pgvector

## ORPHANS & PENDING
None
