# Arquitetura — MLBot

## O que o sistema faz

Gerencia o ciclo de vida de peças OEM de moto: importação de códigos, enriquecimento de dados, precificação e publicação automatizada no Mercado Livre.

## Stack e justificativas

| Escolha | Por quê |
|---------|---------|
| **FastAPI** | Async nativo, validação automática via Pydantic, OpenAPI docs grátis — ideal pra API que vai crescer com integrações externas. |
| **SQLAlchemy 2.0** | ORM maduro com suporte a múltiplos bancos. Facilita migrar de SQLite (dev) pra PostgreSQL (prod) sem mudar código. |
| **SQLite (dev)** | Zero setup, perfeito pra desenvolvimento local. Troca pra PostgreSQL via `DATABASE_URL` no `.env`. |
| **Pydantic Settings** | Configuração tipada via `.env` — sem hardcode, sem risco de credenciais no código. |
| **httpx** | HTTP client moderno com suporte sync/async, timeout configurável. Usado pra chamadas ao ML API. |
| **Ruff** | Linter + formatter mais rápido do ecossistema Python. Substitui flake8, isort, black num binário só. |
| **pytest** | Framework de testes padrão da indústria. TestClient do FastAPI permite testes de integração reais contra SQLite em memória. |

## Estrutura do projeto

```
MLBot/
├── app/
│   ├── main.py              # Entry point FastAPI, registra routers e handlers
│   ├── config.py             # Settings via pydantic-settings (.env)
│   ├── database.py           # Engine SQLAlchemy, SessionLocal, get_db
│   ├── models.py             # Modelos ORM (Product, Listing, MLCredential, etc.)
│   ├── schemas.py            # Schemas Pydantic (request/response)
│   ├── routers/
│   │   ├── batches.py        # Importação de códigos OEM
│   │   ├── products.py       # CRUD de produtos, pricing, imagens
│   │   ├── listings.py       # Geração, validação e publicação de anúncios
│   │   └── auth_ml.py        # OAuth 2.0 com Mercado Livre
│   └── services/
│       └── mercadolivre.py   # Cliente HTTP pro ML API (auth, publish, categories)
├── tests/
│   ├── conftest.py           # Fixtures (DB de teste, TestClient)
│   └── test_batches.py       # Testes do fluxo de importação
├── .env.example              # Template de variáveis de ambiente
├── requirements.txt          # Dependências pinadas
├── ruff.toml                 # Config do linter/formatter
└── pytest.ini                # Config de testes
```

## Fluxo principal

```
Import OEM (.txt) → Normalize → Enrich (dados do produto) → Price → Generate Listing → Validate → Publish (ML API)
```

## Integração Mercado Livre

### Autenticação (OAuth 2.0)

1. `GET /auth/ml/login` — retorna a URL de autorização do ML
2. Usuário autoriza no ML, é redirecionado pra `GET /auth/ml/callback?code=...`
3. App troca o `code` por `access_token` + `refresh_token` via `POST /oauth/token`
4. Tokens armazenados na tabela `ml_credentials`
5. Refresh automático quando o token expira

### Publicação

1. `POST /items` no ML API com: título, categoria, preço (BRL), fotos, atributos
2. Descrição enviada separadamente via `POST /items/{id}/description`
3. Resposta inclui `ml_item_id` e `permalink` do anúncio publicado

## Decisões de design

- **Um token por app** (não por usuário): o MLBot opera como uma conta vendedora única. O modelo `MLCredential` suporta expansão futura pra multi-seller.
- **Sem Alembic ainda**: tabelas criadas via `create_all()`. Alembic será adicionado quando migrar pra PostgreSQL em produção.
- **Sem auth de usuário ainda**: foco atual é a integração ML. Auth interna será implementada quando houver múltiplos operadores.
- **Imagens por URL**: o ML API aceita URLs de imagens no campo `pictures.source`. O storage real de imagens será implementado conforme necessidade (S3, local, etc.).
