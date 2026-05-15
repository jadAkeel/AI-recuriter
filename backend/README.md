# Backend

## Overview
FastAPI backend for AI Recruiter Assistant.

## Environment
Set `DATABASE_URL` for production Postgres, e.g.
`postgresql+asyncpg://user:password@localhost:5432/ai_recruiter`

## Run
- Install dependencies in a virtual environment.
- Start with Uvicorn using `app.main:app`.

## Gmail interview invites
- Set `SMTP_USERNAME`, `SMTP_FROM_EMAIL`, and `SMTP_PASSWORD` in `backend/.env`.
- For Gmail, `SMTP_PASSWORD` must be a 16-character Google App Password, not your normal Gmail password.
- Set `APP_BASE_URL` to a public URL if candidates will open the interview link outside your machine.
- For a quick no-hosting workflow, run [start-public-interview.ps1](/C:/Users/Win11/Desktop/NLP/NLP/scripts/start-public-interview.ps1). It starts the frontend, creates a temporary public tunnel, updates `APP_BASE_URL`, and then starts the backend.

## Docker
- Use docker-compose at repository root to start API + Postgres.
