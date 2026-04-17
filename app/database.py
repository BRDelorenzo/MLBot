from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")

# Defesa em profundidade: M2/M7 já proíbem SQLite em produção via Settings,
# mas bloqueamos aqui também caso alguém instancie engine em outro contexto.
if _is_sqlite and settings.env.lower() == "production":
    raise RuntimeError(
        "SQLite não é permitido em ENV=production. Use Postgres 15+."
    )

connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
