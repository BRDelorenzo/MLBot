#!/usr/bin/env bash
# Backup diário do Postgres para S3/R2.
#
# Variáveis de ambiente esperadas:
#   DATABASE_URL              postgres://user:pass@host:5432/dbname
#   BACKUP_S3_BUCKET          ex: s3://mlbot-backups
#   BACKUP_S3_ENDPOINT        opcional (R2/Minio). Ex: https://xxx.r2.cloudflarestorage.com
#   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
#
# Cron sugerido (cron.d/mlbot-backup):
#   0 3 * * *  root  /opt/mlbot/scripts/backup_postgres.sh >> /var/log/mlbot-backup.log 2>&1

set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL é obrigatório}"
: "${BACKUP_S3_BUCKET:?BACKUP_S3_BUCKET é obrigatório}"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
DOW="$(date -u +%u)"       # 1-7
TMP="$(mktemp -d)"
DUMP="${TMP}/mlbot-${TS}.dump"

cleanup() { rm -rf "${TMP}"; }
trap cleanup EXIT

echo "[$(date -u +%FT%TZ)] pg_dump iniciando"
pg_dump --format=custom --no-owner --no-privileges --compress=9 \
    --file "${DUMP}" "${DATABASE_URL}"

SIZE=$(stat -c%s "${DUMP}" 2>/dev/null || stat -f%z "${DUMP}")
echo "[$(date -u +%FT%TZ)] dump gerado: ${SIZE} bytes"

AWS_ARGS=()
if [[ -n "${BACKUP_S3_ENDPOINT:-}" ]]; then
    AWS_ARGS+=(--endpoint-url "${BACKUP_S3_ENDPOINT}")
fi

# Diário (retenção 30d via lifecycle policy no bucket)
aws "${AWS_ARGS[@]}" s3 cp "${DUMP}" "${BACKUP_S3_BUCKET}/daily/mlbot-${TS}.dump"

# Semanal aos domingos (retenção 1 ano via lifecycle)
if [[ "${DOW}" == "7" ]]; then
    aws "${AWS_ARGS[@]}" s3 cp "${DUMP}" "${BACKUP_S3_BUCKET}/weekly/mlbot-${TS}.dump"
fi

echo "[$(date -u +%FT%TZ)] backup concluído"
