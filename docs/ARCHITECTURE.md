# Arquitetura — notas operacionais

## Bulk enrich — modo atual: single-worker safe

`POST /products/bulk-enrich` cria um `EnrichJob` e dispara `threading.Thread`
in-process (ver [app/services/enrich_jobs.py](../app/services/enrich_jobs.py)).

**Requisito de deploy:** um único processo worker (gunicorn/uvicorn
`--workers 1`). Múltiplos workers significam threads independentes por
processo — um job pode rodar mais de uma vez ou progresso ser conflitante.

**Recuperação de crash (A8):** no startup
([app/bootstrap.py](../app/bootstrap.py) → `reap_stuck_enrich_jobs`), jobs com
`status=running AND started_at < now-1h` são marcados `failed` com
`error_details={"error":"worker_restart"}`. Isso evita jobs zumbis após
SIGTERM/OOM/scale-down.

**Roadmap (quando escalar):** migrar para RQ ou Celery usando o Redis já
presente (A4). O contrato do endpoint não muda — `EnrichJob` continua sendo a
fonte de verdade de progresso.

## CORS / CSRF

Ver [docs/adr/0001-auth-cors-csrf.md](adr/0001-auth-cors-csrf.md).

## Backups

Ver [docs/runbooks/backup-restore.md](runbooks/backup-restore.md).
