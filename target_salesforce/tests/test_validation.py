"""Tests for the schema checks, which need no Salesforce credentials."""

import pytest

from target_salesforce.utils.exceptions import InvalidStreamSchemaError
from target_salesforce.utils.validation import ObjectField, validate_schema_field


def _fields(*fields: ObjectField) -> dict[str, ObjectField]:
    """Key the fields the way the sink does, by the folded name."""
    return {field.name.lower(): field for field in fields}


OBJECT_FIELDS = _fields(
    ObjectField(name="Id", type="id", createable=False, updateable=False),
    ObjectField(name="Name", type="string", createable=True, updateable=True),
    ObjectField(name="External_ID__c", type="string", createable=True, updateable=True),
    ObjectField(
        name="CreatedDate", type="datetime", createable=False, updateable=False
    ),
)


@pytest.mark.parametrize(
    "spelling",
    ["External_ID__c", "External_Id__c", "external_id__c", "EXTERNAL_ID__C"],
)
def test_a_field_resolves_whatever_its_case(spelling):
    """Salesforce accepts any case, so a tap's spelling must not matter."""
    assert OBJECT_FIELDS[spelling.lower()].name == "External_ID__c"
    validate_schema_field(spelling, OBJECT_FIELDS, "upsert", "Account")


def test_an_unknown_field_is_still_rejected():
    """Folding the case must not let a name through that does not exist."""
    with pytest.raises(InvalidStreamSchemaError, match="does not exist"):
        validate_schema_field("Nope__c", OBJECT_FIELDS, "upsert", "Account")


@pytest.mark.parametrize("spelling", ["Id", "id", "ID"])
def test_id_is_recognised_whatever_its_case(spelling):
    """The Id check gates the insert action, so it must see every spelling."""
    validate_schema_field(spelling, OBJECT_FIELDS, "update", "Account")

    with pytest.raises(InvalidStreamSchemaError, match="not createable"):
        validate_schema_field(spelling, OBJECT_FIELDS, "insert", "Account")


def test_a_field_that_cannot_be_created_is_rejected_on_insert():
    """Case folding must not weaken the createable and updateable checks."""
    with pytest.raises(InvalidStreamSchemaError, match="not creatable"):
        validate_schema_field("createddate", OBJECT_FIELDS, "insert", "Account")


def test_sdc_metadata_is_ignored():
    """The SDK's own columns are not Salesforce fields."""
    validate_schema_field("_sdc_batched_at", OBJECT_FIELDS, "upsert", "Account")
