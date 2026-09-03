from __future__ import annotations

from typing import Any, Dict, List

from src.app.core.logging_setup import get_logger

log = get_logger(__name__)


class BaseNormalizer:
    object_name: str = "base"
    output_tables: List[str] = []

    def normalize(self, records: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        raise NotImplementedError

    @staticmethod
    def safe_get(record: Dict[str, Any], key: str, default: Any = None) -> Any:
        if not isinstance(record, dict):
            return default
        value = record.get(key, default)
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else default
        return value

    def get_statistics(self, tables: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        return {name: len(rows) for name, rows in tables.items()}


class AccountNormalizer(BaseNormalizer):
    object_name = "Account"
    output_tables = ["accounts", "account_addresses", "account_teams"]


class ContactNormalizer(BaseNormalizer):
    object_name = "Contact"
    output_tables = ["contacts", "contact_roles"]


class OpportunityNormalizer(BaseNormalizer):
    object_name = "Opportunity"
    output_tables = [
        "opportunities",
        "opportunity_line_items",
        "opportunity_contact_roles",
    ]


class LeadNormalizer(BaseNormalizer):
    object_name = "Lead"
    output_tables = ["leads"]


class CaseNormalizer(BaseNormalizer):
    object_name = "Case"
    output_tables = ["cases", "case_comments"]


class TaskEventNormalizer(BaseNormalizer):
    object_name = "TaskEvent"
    output_tables = ["tasks", "events"]


class CampaignNormalizer(BaseNormalizer):
    object_name = "Campaign"
    output_tables = ["campaigns", "campaign_members"]


class UserNormalizer(BaseNormalizer):
    object_name = "User"
    output_tables = ["users"]


NORMALIZER_REGISTRY: Dict[str, BaseNormalizer] = {
    "Account": AccountNormalizer(),
    "Contact": ContactNormalizer(),
    "Opportunity": OpportunityNormalizer(),
    "OpportunityLineItem": OpportunityNormalizer(),
    "Lead": LeadNormalizer(),
    "Case": CaseNormalizer(),
    "Task": TaskEventNormalizer(),
    "Event": TaskEventNormalizer(),
    "Campaign": CampaignNormalizer(),
    "User": UserNormalizer(),
}

SUPPORTED_OBJECTS_CATALOG: Dict[str, List[str]] = {
    n.object_name: n.output_tables for n in NORMALIZER_REGISTRY.values()
}
