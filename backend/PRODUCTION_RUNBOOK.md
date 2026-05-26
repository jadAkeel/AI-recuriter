# Production Runbook

This runbook covers the minimum paid-pilot operating procedures for the AI Hiring Copilot backend.

## Startup Gate

- Run migrations before the API starts: `RUN_MIGRATIONS=true` on the `api` service.
- Keep `RUN_CV_WORKER_IN_API=false` in production and run `python -m app.worker` as the dedicated worker service.
- The API healthcheck must call `/api/v1/ready`, not `/api/v1/health`.
- Ollama must have these models before the API is ready: `OLLAMA_MODEL`, `OLLAMA_INTERVIEW_MODEL`, `OLLAMA_PARSING_MODEL`, `OLLAMA_EMBEDDING_MODEL`.

## Backfill After Upgrade

Run from the backend container after migrations:

```bash
python scripts/backfill_production_readiness.py --dry-run
python scripts/backfill_production_readiness.py --rebuild-embeddings
```

The backfill normalizes candidate skills, rebuilds `skill_evidence`, optionally rebuilds candidate/job embeddings, and marks stale matches/reports.

## Backup

Back up these assets together so reports and CV files remain consistent:

- PostgreSQL database
- `cv_uploads` volume
- `redis_data` volume if queued task recovery is required
- `ollama_data` volume if you want to avoid model repulls

PowerShell helper creates `postgres.sql` plus volume archives:

```powershell
scripts/backup-production.ps1 -OutputDir C:\backups\nlp-final
```

## Restore

Restore database first, then volumes, then run migrations and backfill dry-run.

PowerShell helper:

```powershell
scripts/restore-production.ps1 -BackupDir C:\backups\nlp-final\<backup-folder>
```

After restore:

```bash
alembic upgrade head
python scripts/backfill_production_readiness.py --dry-run
```

## Provider Outage

- If `/api/v1/ready` reports Ollama or embedding degraded, stop new customer demos and inspect `ollama-bootstrap` logs.
- Do not switch production to `EMBEDDING_PROVIDER=hash`.
- If the LLM provider is down, keep recruiter-visible output marked degraded instead of silently trusting fallback output.

## Redis Outage

- Production queueing must fail clearly when Redis is down.
- Restart Redis and then the `worker` service.
- Check pending CV task statuses before asking users to re-upload.

## DB Migration Rollback

- Take a database backup before `alembic upgrade head`.
- If migration fails, restore the DB backup instead of manually editing schema.
- Re-run `alembic current` and `alembic upgrade head` after fixing the migration.
