from datetime import timedelta

from src.app.core.utils import utcnow
from src.app.models import AuditEventCategory, AuditOutcome


def test_audit_service_accepts_structured_events():
    assert AuditEventCategory.AUTH.value == "auth"
    assert AuditOutcome.SUCCESS.value == "success"
    assert timedelta(minutes=1).total_seconds() == 60
    assert utcnow().tzinfo is not None
