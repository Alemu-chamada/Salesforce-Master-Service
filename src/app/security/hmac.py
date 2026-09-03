from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import Request, Response


class HMACAuthData:
    def __init__(
        self,
        client_id: str,
        role: str,
        signature: str,
        timestamp: str,
        nonce: str,
    ) -> None:
        self.client_id = client_id
        self.role = role
        self.signature = signature
        self.timestamp = timestamp
        self.nonce = nonce


async def hmac_auth_required(request: Request) -> HMACAuthData:
    """Placeholder. Implemented in Phase 2."""
    return HMACAuthData(
        client_id="coordinator",
        role="full",
        signature="phase1-placeholder",
        timestamp="0",
        nonce="phase1-placeholder",
    )


async def hmac_auth_readonly(request: Request) -> HMACAuthData:
    return await hmac_auth_required(request)
