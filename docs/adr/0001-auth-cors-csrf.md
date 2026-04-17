# ADR 0001 — Autenticação, CORS e CSRF

**Status:** aceito
**Data:** 2026-04-14

## Contexto

Definir a postura de segurança de borda do backend FastAPI para proteger sessões
autenticadas contra CSRF sem adicionar complexidade desnecessária.

## Decisão

1. **Autenticação via JWT em `Authorization: Bearer <token>`** — nunca em cookie.
   Requests cross-origin não anexam `Authorization` automaticamente, então
   **CSRF não é um vetor enquanto não usarmos cookies de sessão**.

2. **CORS com whitelist explícita** (`settings.allowed_origins`), CSV via env.
   Em `ENV=production`, o startup **falha** se `ALLOWED_ORIGINS` estiver vazio.

3. **Proibido** `allow_origins=["*"]` combinado com `allow_credentials=True`:
   não satisfaz a spec e abre cross-origin credentials.

4. **Se futuramente migrarmos para cookie `httpOnly`**, adotar double-submit
   CSRF: token em cookie não-httpOnly lido por JS e reenviado em header
   customizado, validado server-side. Neste caso, também:
   - `SameSite=Lax` (ou `Strict` onde possível)
   - `Secure` em prod
   - Proteção extra por origin check

## Consequências

- Frontend separado (web/app/dashboard) precisa declarar sua origem em
  `ALLOWED_ORIGINS` antes de bater no backend.
- Logs de browser com origin não-whitelist retornam 403 de CORS — comportamento
  esperado, não bug.
- Troca futura para cookie auth é um breaking change de segurança, exige ADR
  novo que substitua este.
