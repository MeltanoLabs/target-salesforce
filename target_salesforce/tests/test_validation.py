"""Tests for the stream schema validation against a Salesforce object."""

import pytest

from target_salesforce.utils.exceptions import InvalidStreamSchemaError
from target_salesforce.utils.validation import ObjectField, validate_schema_field

OBJECT_FIELDS = {
    "Id": ObjectField("id", createable=False, updateable=False),
    "Name": ObjectField("string", createable=True, updateable=True),
    "CreatedDate": ObjectField("datetime", createable=False, updateable=False),
    "ReadOnly": ObjectField("string", createable=False, updateable=True),
}


def _validate(field_name, action):
    validate_schema_field(field_name, OBJECT_FIELDS, action, "Account")


@pytest.mark.parametrize("action", ["insert", "update", "upsert"])
def test_a_writable_field_passes(action):
    """A field that the object can both create and update suits every action."""
    _validate("Name", action)


@pytest.mark.parametrize("action", ["insert", "update", "upsert", "delete"])
def test_sdc_metadata_is_ignored(action):
    """An _sdc field never reaches Salesforce, so it needs no counterpart."""
    _validate("_sdc_extracted_at", action)


@pytest.mark.parametrize("action", ["update", "upsert", "delete", "hard_delete"])
def test_id_passes_for_every_action_but_insert(action):
    """Id addresses an existing record, so only insert has no use for it."""
    _validate("Id", action)


def test_id_is_rejected_on_insert():
    """Salesforce assigns the Id, so a record cannot arrive carrying one."""
    with pytest.raises(InvalidStreamSchemaError, match="not createable"):
        _validate("Id", "insert")


def test_an_unknown_field_is_rejected():
    """A field absent from the object would fail at the API instead."""
    with pytest.raises(InvalidStreamSchemaError, match="does not exist"):
        _validate("Nope", "update")


@pytest.mark.parametrize("action", ["update", "upsert"])
def test_a_field_the_object_cannot_update_is_rejected(action):
    """An update carrying a read-only field would fail at the API."""
    with pytest.raises(InvalidStreamSchemaError, match="not updatable"):
        _validate("CreatedDate", action)


@pytest.mark.parametrize("action", ["insert", "upsert"])
def test_a_field_the_object_cannot_create_is_rejected(action):
    """An insert carrying a non-createable field would fail at the API."""
    with pytest.raises(InvalidStreamSchemaError, match="not creatable"):
        _validate("ReadOnly", action)


@pytest.mark.parametrize("action", ["delete", "hard_delete"])
def test_a_delete_takes_nothing_but_id(action):
    """A delete addresses records by Id, so any other field is a mistake."""
    with pytest.raises(InvalidStreamSchemaError, match="should only include Id"):
        _validate("Name", action)
