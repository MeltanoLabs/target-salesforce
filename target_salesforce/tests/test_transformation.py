"""Tests for the record transformation, which needs no Salesforce credentials."""

from target_salesforce.utils.transformation import transform_record
from target_salesforce.utils.validation import ObjectField

OBJECT_FIELDS = {
    field.name.lower(): field
    for field in (
        ObjectField(name="Name", type="string", createable=True, updateable=True),
        ObjectField(
            name="External_ID__c", type="string", createable=True, updateable=True
        ),
    )
}


def test_a_key_becomes_the_name_salesforce_spells():
    """The Bulk API header must not depend on how a tap spells a column."""
    record = {"name": "Acme Ltd", "EXTERNAL_ID__C": "acct-4417"}

    assert transform_record(record, OBJECT_FIELDS) == {
        "Name": "Acme Ltd",
        "External_ID__c": "acct-4417",
    }


def test_a_key_that_matches_no_field_is_left_alone():
    """Validation rejects an unknown field, so nothing is silently renamed."""
    assert transform_record({"Nope__c": "x"}, OBJECT_FIELDS) == {"Nope__c": "x"}


def test_a_none_value_survives_with_its_key_rewritten():
    """A null clears the field, and it must still reach the right column."""
    assert transform_record({"name": None}, OBJECT_FIELDS) == {"Name": None}
