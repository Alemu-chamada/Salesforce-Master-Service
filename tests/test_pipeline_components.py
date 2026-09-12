from pathlib import Path

import pytest

from src.app.normalization.normalizers import (
    NORMALIZER_REGISTRY,
    SUPPORTED_OBJECTS_CATALOG,
    AccountNormalizer,
    LeadNormalizer,
    OpportunityLineItemNormalizer,
    OpportunityNormalizer,
)
from src.app.salesforce.queries import query_for
from src.app.services.batch_file_service import BatchFileService
from src.app.storage.minio_client import MinIOClient


def test_batch_file_service_streams_and_reads_csv(tmp_path):
    service = BatchFileService(str(tmp_path))
    info = service.save_results_to_disk("scan-1", "Account", iter(["Id,Name\n", "001,Acme\n"]))
    assert info["record_count"] == 1
    assert service.read_csv_file(info["path"]) == [{"Id": "001", "Name": "Acme"}]
    assert service.get_file_info("scan-1")["total_records"] == 1
    service.cleanup_extracted_files("scan-1")
    assert not Path(info["path"]).exists()


def test_normalizers_preserve_ids_and_relationships():
    account_tables = AccountNormalizer().normalize([{"Id": "001", "Name": "Acme", "BillingCity": "Boston"}])
    assert account_tables["accounts"][0]["id"] == "001"
    assert account_tables["account_addresses"][0]["address_type"] == "billing"

    leads = LeadNormalizer().normalize([{"Id": "00Q", "Name": "Ada", "Status": "Open"}])
    assert leads["leads"][0]["id"] == "00Q"
    assert leads["leads"][0]["status"] == "Open"


def test_child_queries_are_partitioned_per_object():
    assert "FROM OpportunityLineItems" not in query_for("Opportunity")
    assert "FROM OpportunityContactRoles" not in query_for("Opportunity")
    assert "FROM CaseComments" not in query_for("Case")
    assert "FROM CampaignMembers" not in query_for("Campaign")
    assert "FROM OpportunityLineItem" in query_for("OpportunityLineItem")
    assert "FROM OpportunityContactRole" in query_for("OpportunityContactRole")
    assert "FROM CaseComment" in query_for("CaseComment")
    assert "FROM CampaignMember" in query_for("CampaignMember")

    opportunity_tables = OpportunityNormalizer().normalize([
        {"Id": "006", "Name": "Big deal", "StageName": "Closed Won"}
    ])
    assert opportunity_tables["opportunities"][0]["id"] == "006"
    assert "opportunity_line_items" not in opportunity_tables

    line_item_tables = OpportunityLineItemNormalizer().normalize([
        {"Id": "00k", "OpportunityId": "006", "Name": "Widget"}
    ])
    assert line_item_tables["opportunity_line_items"][0]["opportunity_id"] == "006"

    role_tables = NORMALIZER_REGISTRY["OpportunityContactRole"].normalize([
        {"Id": "ocr", "OpportunityId": "006", "ContactId": "003", "Role": "Decision Maker", "IsPrimary": "true"}
    ])
    assert role_tables["opportunity_contact_roles"][0]["opportunity_id"] == "006"

    assert SUPPORTED_OBJECTS_CATALOG["Task"] == ["tasks", "events"]
    assert SUPPORTED_OBJECTS_CATALOG["Event"] == ["tasks", "events"]
    assert SUPPORTED_OBJECTS_CATALOG["OpportunityLineItem"] == ["opportunity_line_items"]


def test_batch_file_service_does_not_leave_partial_downloads(tmp_path):
    service = BatchFileService(str(tmp_path))

    def broken_stream():
        yield "Id,Name\n"
        raise OSError("network dropped")

    with pytest.raises(OSError):
        service.save_results_to_disk("scan-1", "Account", broken_stream())

    final_path = tmp_path / "scan-1" / "extracted" / "Account.csv"
    assert not final_path.exists()
    assert not any((tmp_path / "scan-1" / "extracted").glob("Account*.part"))


def test_minio_upload_uses_required_partition_key(monkeypatch, tmp_path):
    calls = []
    client = MinIOClient("minio:9000", "access", "secret", "bucket")
    monkeypatch.setattr(client, "upload_file", lambda path, key: calls.append((path, key)))
    keys = client.upload_normalized_data("scan-1", "org-1", "2026-09-04", {"accounts": str(tmp_path / "accounts.parquet")})
    assert keys == ["salesforce/accounts/glynac_organization_id=org-1/processing_date=2026-09-04/accounts.parquet"]
    assert calls[0][1] == keys[0]
