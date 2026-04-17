"""Endpoints de consulta de jobs assíncronos (bulk-enrich etc.)."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EnrichJob, User
from app.services.auth import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.query(EnrichJob).filter(EnrichJob.id == job_id).first()
    if not job or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    error_details = None
    if job.error_details:
        try:
            error_details = json.loads(job.error_details)
        except ValueError:
            error_details = job.error_details

    return {
        "job_id": job.id,
        "batch_id": job.batch_id,
        "status": job.status.value,
        "total": job.total,
        "processed": job.processed,
        "succeeded": job.succeeded,
        "failed": job.failed,
        "error_details": error_details,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
    }
