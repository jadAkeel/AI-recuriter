param(
    [Parameter(Mandatory=$true)]
    [string]$BackupDir,
    [string]$ComposeFile = "docker-compose.prod.yml",
    [string]$ProjectName = "nlpfinalversion"
)

$ErrorActionPreference = "Stop"

docker compose -f $ComposeFile stop api worker nginx
Get-Content -Path (Join-Path $BackupDir "postgres.sql") | docker compose -f $ComposeFile exec -T db psql -U postgres -d ai_recruiter
docker run --rm -v "${ProjectName}_cv_uploads:/data" -v "$BackupDir:/backup" alpine sh -c "rm -rf /data/* && tar xzf /backup/cv_uploads.tgz -C /data"
docker run --rm -v "${ProjectName}_redis_data:/data" -v "$BackupDir:/backup" alpine sh -c "rm -rf /data/* && tar xzf /backup/redis_data.tgz -C /data"
docker run --rm -v "${ProjectName}_ollama_data:/data" -v "$BackupDir:/backup" alpine sh -c "rm -rf /data/* && tar xzf /backup/ollama_data.tgz -C /data"
docker compose -f $ComposeFile up -d

"Restore completed from: $BackupDir"
