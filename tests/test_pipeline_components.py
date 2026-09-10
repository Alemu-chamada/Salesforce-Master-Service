from pathlib import Path

from src.app.normalization.normalizers import (
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


def test_child_queries_and_normalizers_preserve_relationships():
    opportunity_query = query_for("Opportunity")
    assert "FROM OpportunityLineItems" in opportunity_query
    assert "FROM OpportunityContactRoles" in opportunity_query
    assert "FROM CaseComments" in query_for("Case")
    assert "FROM CampaignMembers" in query_for("Campaign")

    opportunity_tables = OpportunityNormalizer().normalize([
        {
            "Id": "006",
            "OpportunityLineItems": {"records": [{"Id": "00k", "OpportunityId": "006", "Name": "Widget"}]},
            "OpportunityContactRoles": {"records": [{"Id": "ocr", "ContactId": "003", "Role": "Decision Maker"}]},
        }
    ])
    assert opportunity_tables["opportunity_line_items"][0]["id"] == "00k"
    assert opportunity_tables["opportunity_contact_roles"][0]["contactid"] == "003"

    line_item_tables = OpportunityLineItemNormalizer().normalize([
        {"Id": "00k", "OpportunityId": "006", "Name": "Widget"}
    ])
    assert line_item_tables["opportunity_line_items"][0]["opportunity_id"] == "006"
    assert SUPPORTED_OBJECTS_CATALOG["Task"] == ["tasks", "events"]
    assert SUPPORTED_OBJECTS_CATALOG["Event"] == ["tasks", "events"]
    assert SUPPORTED_OBJECTS_CATALOG["OpportunityLineItem"] == ["opportunity_line_items"]


def test_minio_upload_uses_required_partition_key(monkeypatch, tmp_path):
    calls = []
    client = MinIOClient("minio:9000", "access", "secret", "bucket")
    monkeypatch.setattr(client, "upload_file", lambda path, key: calls.append((path, key)))
    keys = client.upload_normalized_data("scan-1", "org-1", "2026-09-04", {"accounts": str(tmp_path / "accounts.parquet")})
    assert keys == ["salesforce/accounts/glynac_organization_id=org-1/processing_date=2026-09-04/accounts.parquet"]
    assert calls[0][1] == keys[0]
