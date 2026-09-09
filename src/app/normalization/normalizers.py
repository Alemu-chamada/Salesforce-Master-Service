from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

from src.app.core.logging_setup import get_logger

log = get_logger(__name__)


class BaseNormalizer:
    object_name: ClassVar[str] = "base"
    output_tables: ClassVar[list[str]] = []

    def normalize(self, records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        raise NotImplementedError

    @staticmethod
    def safe_get(record: dict[str, Any], key: str, default: Any = None) -> Any:
        if not isinstance(record, dict):
            return default
        value = record.get(key, default)
        if isinstance(value, str):
            stripped = value.strip()
            return stripped if stripped else default
        return value

    def get_statistics(self, tables: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        return {name: len(rows) for name, rows in tables.items()}

    def save_to_files(self, tables: dict[str, list[dict[str, Any]]], directory: str, output_format: str = "parquet") -> dict[str, str]:
        output_dir = Path(directory)
        output_dir.mkdir(parents=True, exist_ok=True)
        if output_format not in {"json", "parquet"}:
            raise ValueError("output_format must be json or parquet")
        paths = {}
        for table_name, rows in tables.items():
            path = output_dir / f"{table_name}.{output_format}"
            if output_format == "json":
                path.write_text(json.dumps(rows, default=str), encoding="utf-8")
            else:
                import pandas as pd
                pd.DataFrame(rows).to_parquet(path, index=False)
            paths[table_name] = str(path)
        return paths

    def _row(self, record: dict[str, Any], keys: list[str]) -> dict[str, Any]:
        return {key.lower(): self.safe_get(record, key) for key in keys}

    def _children(self, record: dict[str, Any], relationship: str) -> list[dict[str, Any]]:
        value = record.get(relationship) or record.get(relationship.lower()) or []
        if isinstance(value, dict):
            value = value.get("records", [])
        return value if isinstance(value, list) else []


class AccountNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Account"
    output_tables: ClassVar[list[str]] = ["accounts", "account_addresses", "account_teams"]

    def normalize(self, records):
        accounts, addresses, teams = [], [], []
        for record in records:
            account = self._row(record, ["Id", "Name", "AccountNumber", "Type", "Industry", "Phone", "Website", "OwnerId", "ParentId", "CreatedDate", "LastModifiedDate"])
            accounts.append(account)
            for prefix, kind in (("Billing", "billing"), ("Shipping", "shipping")):
                address = self._row(record, [f"{prefix}Street", f"{prefix}City", f"{prefix}State", f"{prefix}PostalCode", f"{prefix}Country"])
                if any(value is not None for value in address.values()):
                    addresses.append({"account_id": account["id"], "address_type": kind, **address})
            if account.get("ownerid"):
                teams.append({"account_id": account["id"], "user_id": account["ownerid"], "role": "owner"})
        return {"accounts": accounts, "account_addresses": addresses, "account_teams": teams}


class ContactNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Contact"
    output_tables: ClassVar[list[str]] = ["contacts", "contact_roles"]

    def normalize(self, records):
        contacts, roles = [], []
        for record in records:
            contact = self._row(record, ["Id", "AccountId", "FirstName", "LastName", "Name", "Email", "Phone", "MobilePhone", "Title", "Department", "OwnerId", "CreatedDate", "LastModifiedDate"])
            contacts.append(contact)
            if contact.get("accountid"):
                roles.append({"contact_id": contact["id"], "account_id": contact["accountid"], "role": "contact"})
        return {"contacts": contacts, "contact_roles": roles}


class OpportunityNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Opportunity"
    output_tables: ClassVar[list[str]] = [
        "opportunities",
        "opportunity_line_items",
        "opportunity_contact_roles",
    ]

    def normalize(self, records):
        opportunities, line_items, roles = [], [], []
        for record in records:
            opportunity = self._row(record, ["Id", "AccountId", "Name", "StageName", "Amount", "CloseDate", "Probability", "Type", "LeadSource", "OwnerId", "CreatedDate", "LastModifiedDate"])
            opportunities.append(opportunity)
            for item in self._children(record, "OpportunityLineItems"):
                line_items.append({"opportunity_id": opportunity["id"], **self._row(item, ["Id", "Product2Id", "ProductCode", "Name", "Quantity", "UnitPrice", "TotalPrice", "ServiceDate"])})
            for role in self._children(record, "OpportunityContactRoles"):
                roles.append({"opportunity_id": opportunity["id"], **self._row(role, ["ContactId", "Role", "IsPrimary"])})
        return {"opportunities": opportunities, "opportunity_line_items": line_items, "opportunity_contact_roles": roles}


class LeadNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Lead"
    output_tables: ClassVar[list[str]] = ["leads"]

    def normalize(self, records):
        return {"leads": [self._row(record, ["Id", "FirstName", "LastName", "Name", "Company", "Title", "Email", "Phone", "MobilePhone", "Status", "LeadSource", "Industry", "Street", "City", "State", "PostalCode", "Country", "OwnerId", "CreatedDate", "LastModifiedDate"]) for record in records]}


class CaseNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Case"
    output_tables: ClassVar[list[str]] = ["cases", "case_comments"]

    def normalize(self, records):
        cases, comments = [], []
        for record in records:
            case = self._row(record, ["Id", "AccountId", "ContactId", "CaseNumber", "Subject", "Description", "Status", "Priority", "Origin", "Type", "Reason", "OwnerId", "CreatedDate", "LastModifiedDate"])
            cases.append(case)
            for comment in self._children(record, "CaseComments"):
                comments.append({"case_id": case["id"], **self._row(comment, ["Id", "CommentBody", "CreatedDate", "CreatedById"])})
        return {"cases": cases, "case_comments": comments}


class TaskEventNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "TaskEvent"
    output_tables: ClassVar[list[str]] = ["tasks", "events"]

    def normalize(self, records):
        tasks, events = [], []
        for record in records:
            target = events if record.get("StartDateTime") or record.get("startdatetime") else tasks
            target.append(self._row(record, ["Id", "WhoId", "WhatId", "OwnerId", "Subject", "Description", "Status", "Priority", "ActivityDate", "CompletedDateTime", "StartDateTime", "EndDateTime", "IsAllDayEvent", "Location", "CreatedDate", "LastModifiedDate"]))
        return {"tasks": tasks, "events": events}


class CampaignNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "Campaign"
    output_tables: ClassVar[list[str]] = ["campaigns", "campaign_members"]

    def normalize(self, records):
        campaigns, members = [], []
        for record in records:
            campaign = self._row(record, ["Id", "Name", "Type", "Status", "StartDate", "EndDate", "IsActive", "OwnerId", "CreatedDate", "LastModifiedDate"])
            campaigns.append(campaign)
            for member in self._children(record, "CampaignMembers"):
                members.append({"campaign_id": campaign["id"], **self._row(member, ["Id", "LeadId", "ContactId", "Status", "HasResponded", "FirstRespondedDate"])})
        return {"campaigns": campaigns, "campaign_members": members}


class UserNormalizer(BaseNormalizer):
    object_name: ClassVar[str] = "User"
    output_tables: ClassVar[list[str]] = ["users"]

    def normalize(self, records):
        return {"users": [self._row(record, ["Id", "Username", "FirstName", "LastName", "Name", "Email", "IsActive", "UserRoleId", "ProfileId", "Department", "Title", "CreatedDate", "LastModifiedDate"]) for record in records]}


NORMALIZER_REGISTRY: dict[str, BaseNormalizer] = {
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

SUPPORTED_OBJECTS_CATALOG: dict[str, list[str]] = {
    n.object_name: n.output_tables for n in NORMALIZER_REGISTRY.values()
}
