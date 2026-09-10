from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.app.db.session import get_db
from src.app.schemas.common import NormalizationOptions, SupportedObjectInfo
from src.app.security.hmac import hmac_auth_readonly, hmac_auth_required
from src.app.services.job_service import JobService
from src.app.services.normalization_service import NormalizationService

router = APIRouter()


def _norm_service(db: Session = Depends(get_db)) -> NormalizationService:
    return NormalizationService(db, JobService(db))


@router.post("/{scan_id}/normalize", dependencies=[Depends(hmac_auth_required)])
async def normalize_scan(
    scan_id: str,
    options: NormalizationOptions,
    svc: NormalizationService = Depends(_norm_service),
) -> dict[str, Any]:
    try:
        return await svc.normalize_scan(scan_id, options.output_format, options.save_to_disk, options.upload_to_minio, options.processing_date)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/{scan_id}/normalize/{object_name}",
    dependencies=[Depends(hmac_auth_required)],
)
async def normalize_single_object(
    scan_id: str,
    object_name: str,
    svc: NormalizationService = Depends(_norm_service),
) -> dict[str, Any]:
    try:
        return await svc.normalize_single_object(scan_id, object_name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{scan_id}/tables", dependencies=[Depends(hmac_auth_readonly)])
async def list_normalized_tables(
    scan_id: str,
    svc: NormalizationService = Depends(_norm_service),
) -> list[dict[str, Any]]:
    return svc.list_normalized_tables(scan_id)


@router.get("/supported-objects", dependencies=[Depends(hmac_auth_readonly)])
async def get_supported_objects() -> list[SupportedObjectInfo]:
    catalog = NormalizationService.supported_objects()
    return [SupportedObjectInfo(**item) for item in catalog]
