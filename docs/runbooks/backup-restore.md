# Runbook — Backup e Restore Postgres

## Backups

- **Script:** [scripts/backup_postgres.sh](../../scripts/backup_postgres.sh)
- **Frequência:** diário às 03:00 UTC
- **Retenção:** 30 dias (diário) + 52 semanas (semanal aos domingos)
- **Destino:** `s3://mlbot-backups/{daily,weekly}/mlbot-<ts>.dump`
- **Formato:** `pg_dump --format=custom --compress=9`

### Lifecycle sugerida do bucket

```
daily/   -> Expire após 30 dias
weekly/  -> Expire após 365 dias
```

### Variáveis (cron/.env do host de backup)

```
DATABASE_URL=postgres://user:pass@db.internal:5432/mlbot
BACKUP_S3_BUCKET=s3://mlbot-backups
BACKUP_S3_ENDPOINT=https://<account>.r2.cloudflarestorage.com   # R2
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
```

## Point-in-time recovery

Habilitar WAL archiving se o managed-postgres (RDS/Neon/Supabase) não fornecer
PITR nativo:

```
archive_mode = on
archive_command = 'aws s3 cp %p s3://mlbot-wal/%f'
wal_level = replica
```

## Restore

1. **Baixar dump:**
   ```bash
   aws s3 cp s3://mlbot-backups/daily/mlbot-20260414T030000Z.dump ./restore.dump
   ```
2. **Criar DB limpo:**
   ```bash
   createdb mlbot_restore
   ```
3. **Restaurar:**
   ```bash
   pg_restore --no-owner --no-privileges \
       --dbname=postgres://user:pass@host/mlbot_restore ./restore.dump
   ```
4. **Validar:**
   - `SELECT count(*) FROM users;`
   - `SELECT count(*) FROM products;`
   - Subir app apontando para `mlbot_restore` e fazer smoke test.

## Teste mensal

Primeira segunda-feira de cada mês: executar restore em ambiente `staging-restore`
a partir do backup mais recente. Checklist:

- [ ] Dump baixado e íntegro (`pg_restore --list` não falha)
- [ ] Restore completo sem erros
- [ ] Migrations `alembic current` coincide com produção
- [ ] Smoke test: login, listar produtos, criar lote

Registrar resultado no canal `#ops` com data e duração.
