import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import MLCredential, User
from app.schemas import MLAuthURL
from app.services.auth import get_current_user
from app.services.mercadolivre import MLAPIError, exchange_code_for_token, get_auth_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/ml", tags=["auth-ml"])


@router.get("/login", response_model=MLAuthURL)
def ml_login(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return {"auth_url": get_auth_url(db, user.id)}


@router.get("/callback")
def ml_callback(
    code: str = Query(...),
    state: str = Query(...),
    db: Session = Depends(get_db),
):
    """Endpoint de redirect do OAuth ML (navegação do browser).

    Faz a troca do code por token uma única vez e redireciona o usuário de volta
    para a interface — nunca devolve JSON cru, evitando o consumo duplo do code.
    """
    try:
        exchange_code_for_token(code, db, state=state)
    except MLAPIError as exc:
        logger.warning("Callback OAuth ML falhou: %s", exc.detail)
        return RedirectResponse(url="/?ml=error", status_code=303)

    return RedirectResponse(url="/?ml=connected", status_code=303)


@router.get("/status")
def ml_auth_status(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    try:
        credential = db.query(MLCredential).filter(MLCredential.user_id == user.id).first()
        if not credential or not credential.access_token_encrypted:
            return {"authenticated": False, "detail": "Nenhum token encontrado. Acesse /auth/ml/login para autenticar."}

        from datetime import UTC, datetime
        now = datetime.now(UTC).replace(tzinfo=None)
        expired = now >= credential.expires_at

        return {
            "authenticated": True,
            "ml_user_id": credential.ml_user_id,
            "expired": expired,
            "expires_at": credential.expires_at.isoformat(),
        }
    except Exception:
        logger.exception("Erro em /auth/ml/status")
        raise
