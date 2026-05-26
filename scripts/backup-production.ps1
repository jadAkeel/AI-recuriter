param(
    [Parameter(Mandatory=$true)]
    [string]$OutputDir,
    [string]$ComposeFile = "docker-compose.prod.yml",
    [string]$ProjectName = "nlpfinalversion"
)

$ErrorActionPreference = "Stop"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $OutputDir $timestamp
New-Item -ItemType Directory -Path $backupRoot | Out-Null

docker compose -f $ComposeFile exec -T db pg_dump -U postgres -d ai_recruiter --format=plain --no-owner --no-privileges | Out-File -Encoding utf8 -FilePath (Join-Path $backupRoot "postgres.sql")
docker run --rm -v "${ProjectName}_cv_uploads:/data" -v "$backupRoot:/backup" alpine tar czf /backup/cv_uploads.tgz -C /data .
docker run --rm -v "${ProjectName}_redis_data:/data" -v "$backupRoot:/backup" alpine tar czf /backup/redis_data.tgz -C /data .
docker run --rm -v "${ProjectName}_ollama_data:/data" -v "$backupRoot:/backup" alpine tar czf /backup/ollama_data.tgz -C /data .

"Backup completed: $backupRoot"
