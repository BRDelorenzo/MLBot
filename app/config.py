from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # Database
    database_url: str = "sqlite:///./oem_ml.db"

    # Mercado Livre OAuth
    ml_app_id: str = ""
    ml_client_secret: str = ""
    ml_redirect_uri: str = "http://localhost:8000/auth/ml/callback"

    # Mercado Livre API
    ml_api_base_url: str = "https://api.mercadolibre.com"
    ml_auth_url: str = "https://auth.mercadolivre.com.br/authorization"
    ml_site_id: str = "MLB"

    # Criptografia de tokens
    encryption_key: str = ""

    # Upload de imagens
    upload_dir: str = "uploads"
    max_image_size_mb: int = 10

    # AI / Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # JWT Auth
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24

    # Knowledge Base
    kb_upload_dir: str = "uploads/kb"
    kb_max_pdf_size_mb: int = 100
    kb_max_docs_per_tenant: int = 50
    kb_max_total_bytes_per_tenant: int = 2 * 1024 * 1024 * 1024  # 2GB

    # Proxy reverso confiável (habilita leitura de X-Forwarded-For)
    trusted_proxy: bool = False

    # CSV dos IPs dos proxies permitidos a setar X-Forwarded-For.
    # Ex: "10.0.0.0/8,172.16.0.0/12". Vazio = aceita qualquer peer (use só em dev).
    trusted_proxies: str = ""

    def trusted_proxy_list(self) -> list[str]:
        return [p.strip() for p in self.trusted_proxies.split(",") if p.strip()]

    # Rate limit cross-worker. Em dev pode ficar vazio (memory in-process).
    # Em produção multi-worker: defina algo como "redis://localhost:6379/0".
    redis_url: str = ""

    # Ambiente: "development" | "production". Controla validações estritas.
    env: str = "development"

    # CORS — whitelist explícita de origens. Aceita CSV via env:
    # ALLOWED_ORIGINS="https://app.meudominio.com,https://admin.meudominio.com"
    allowed_origins: str = ""

    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        if self.env.lower() != "production":
            return self

        errors: list[str] = []
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            errors.append("JWT_SECRET precisa ter ao menos 32 caracteres em produção.")
        if not self.encryption_key:
            errors.append("ENCRYPTION_KEY obrigatória em produção.")
        if self.database_url.startswith("sqlite"):
            errors.append("DATABASE_URL não pode ser SQLite em produção.")
        if not self.cors_origins():
            errors.append(
                "ALLOWED_ORIGINS obrigatório em produção (CSV de origens permitidas)."
            )

        if errors:
            raise ValueError(
                "Configuração inválida para ENV=production:\n  - "
                + "\n  - ".join(errors)
            )
        return self


settings = Settings()
