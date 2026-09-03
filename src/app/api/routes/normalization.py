from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.app.db.session import get_db
from src.app.schemas.common import NormalizationOptions, SupportedObjectInfo
from src.app.security.hmac import hmac_auth_required, hmac_auth_readonly
from src.app.services.job_service import JobService
from src.app.services.normalization_service import NormalizationService

router = APIRouter(dependencies=[Depends(hmac_auth_readonly)])


def _norm_service(db: Session = Depends(get_db)) -> NormalizationService:
    return NormalizationService(db, JobService(db))


@router.post("/{scan_id}/normalize", dependencies=[Depends(hmac_auth_required)])
async def normalize_scan(
    scan_id: str,
    options: NormalizationOptions,
    svc: NormalizationService = Depends(_norm_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="normalize_scan implemented in Phase 3")


@router.post(
    "/{scan_id}/normalize/{object_name}",
    dependencies=[Depends(hmac_auth_required)],
)
async def normalize_single_object(
    scan_id: str,
    object_name: str,
    svc: NormalizationService = Depends(_norm_service),
) -> Dict[str, Any]:
    raise HTTPException(status_code=501, detail="normalize_single_object implemented in Phase 3")


@router.get("/{scan_id}/tables")
async def list_normalized_tables(
    scan_id: str,
    svc: NormalizationService = Depends(_norm_service),
) -> List[Dict[str, Any]]:
    return svc.list_normalized_tables(scan_id)


@router.get("/supported-objects")
async def get_supported_objects() -> List[SupportedObjectInfo]:
    catalog = NormalizationService.supported_objects()
    return [SupportedObjectInfo(**item) for item in catalog]
