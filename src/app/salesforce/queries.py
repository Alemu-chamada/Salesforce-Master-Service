from __future__ import annotations

SOQL_QUERIES: dict[str, str] = {
    "Account": "SELECT Id, Name, AccountNumber, Type, Industry, Phone, Website, BillingStreet, BillingCity, BillingState, BillingPostalCode, BillingCountry, ShippingStreet, ShippingCity, ShippingState, ShippingPostalCode, ShippingCountry, OwnerId, ParentId, CreatedDate, LastModifiedDate FROM Account",
    "Contact": "SELECT Id, AccountId, FirstName, LastName, Name, Email, Phone, MobilePhone, Title, Department, MailingStreet, MailingCity, MailingState, MailingPostalCode, MailingCountry, OwnerId, CreatedDate, LastModifiedDate FROM Contact",
    "Opportunity": "SELECT Id, AccountId, Name, StageName, Amount, CloseDate, Probability, Type, LeadSource, OwnerId, CreatedDate, LastModifiedDate FROM Opportunity",
    "OpportunityLineItem": "SELECT Id, OpportunityId, Product2Id, ProductCode, Name, Quantity, UnitPrice, TotalPrice, ServiceDate, CreatedDate, LastModifiedDate FROM OpportunityLineItem",
    "Lead": "SELECT Id, FirstName, LastName, Name, Company, Title, Email, Phone, MobilePhone, Status, LeadSource, Industry, Street, City, State, PostalCode, Country, OwnerId, CreatedDate, LastModifiedDate FROM Lead",
    "Case": "SELECT Id, AccountId, ContactId, CaseNumber, Subject, Description, Status, Priority, Origin, Type, Reason, OwnerId, CreatedDate, LastModifiedDate FROM Case",
    "Task": "SELECT Id, WhoId, WhatId, OwnerId, Subject, Description, Status, Priority, ActivityDate, CompletedDateTime, CreatedDate, LastModifiedDate FROM Task",
    "Event": "SELECT Id, WhoId, WhatId, OwnerId, Subject, Description, StartDateTime, EndDateTime, IsAllDayEvent, Location, CreatedDate, LastModifiedDate FROM Event",
    "Campaign": "SELECT Id, Name, Type, Status, StartDate, EndDate, IsActive, NumberOfLeads, NumberOfContacts, NumberOfResponses, NumberOfWonOpportunities, AmountAllOpportunities, OwnerId, CreatedDate, LastModifiedDate FROM Campaign",
    "User": "SELECT Id, Username, FirstName, LastName, Name, Email, IsActive, UserRoleId, ProfileId, Department, Title, CreatedDate, LastModifiedDate FROM User",
}


def query_for(object_name: str) -> str:
    try:
        return SOQL_QUERIES[object_name]
    except KeyError as exc:
        raise ValueError(f"unsupported Salesforce object: {object_name}") from exc