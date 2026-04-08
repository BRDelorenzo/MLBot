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


settings = Settings()
