from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from src.app.core.config import get_settings
from src.app.salesforce.auth_client import SalesforceAuthClient
from src.app.salesforce.exceptions import (
    SalesforceAPIError,
    SalesforceAuthenticationError,
    SalesforceForbiddenError,
    SalesforceInvalidCredentialsError,
    SalesforceInvalidRequestError,
    SalesforceServerError,
    SalesforceTimeoutError,
    SalesforceUnauthorizedError,
)
from src.app.schemas.common import CredentialsValidationResponse, SalesforceCredentials
from src.app.security.hmac import hmac_auth_required

router = APIRouter(dependencies=[Depends(hmac_auth_required)])


def _auth_client() -> SalesforceAuthClient:
    return SalesforceAuthClient(get_settings())


def _translate(err: SalesforceAPIError) -> HTTPException:
    """Map structured Salesforce errors to HTTP statuses suitable for the API caller."""
    message = err.message
    detail: dict[str, Any] = {
        "detail": message,
        "error_code": err.error_code,
        "retryable": bool(err.retryable),
    }
    if isinstance(err, SalesforceInvalidCredentialsError):
        return HTTPException(status_code=401, detail=detail)
    if isinstance(err, SalesforceUnauthorizedError):
        return HTTPException(status_code=401, detail=detail)
    if isinstance(err, SalesforceForbiddenError):
        return HTTPException(status_code=403, detail=detail)
    if isinstance(err, SalesforceInvalidRequestError):
        return HTTPException(status_code=400, detail=detail)
    if isinstance(err, SalesforceTimeoutError):
        return HTTPException(status_code=504, detail=detail)
    if isinstance(err, (SalesforceServerError, SalesforceAuthenticationError)):
        return HTTPException(status_code=502 if err.retryable else 500, detail=detail)
    return HTTPException(status_code=500, detail=detail)


@router.post("/validate-credentials")
async def validate_credentials(
    request: SalesforceCredentials,
    http_request: Request,
    auth_client: SalesforceAuthClient = Depends(_auth_client),
) -> CredentialsValidationResponse:
    creds: dict[str, Any] = request.model_dump(exclude_unset=True)
    try:
        result = await auth_client.validate_credentials(creds)
    except SalesforceAPIError as err:
        raise _translate(err) from err
    except Exception as err:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=500,
            detail={
                "detail": f"credentials validation failed: {err.__class__.__name__}",
                "error_code": "UNEXPECTED_ERROR",
                "retryable": False,
            },
        ) from err
    finally:
        auth_client.clear_cache()
    identity = result.get("identity")
    return CredentialsValidationResponse(
        valid=bool(result.get("valid")),
        error=None,
        identity=identity,
    )
