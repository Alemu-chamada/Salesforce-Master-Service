from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from src.app.security.hmac import HMACAuthData, hmac_auth_readonly

router = APIRouter(dependencies=[Depends(hmac_auth_readonly)])


@router.get("/verify")
async def verify_key(
    request: Request, auth: HMACAuthData = Depends(hmac_auth_readonly)
) -> dict[str, Any]:
    return {
        "client_id": auth.client_id,
        "role": auth.role,
        "signature_valid": True,
    }
