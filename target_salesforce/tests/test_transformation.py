"""Tests for the conversion of date and datetime values into strings."""

import datetime

import pytest

from target_salesforce.utils.transformation import transform_record
from target_salesforce.utils.validation import ObjectField

UTC = datetime.timezone.utc

OBJECT_FIELDS = {
    "Birthdate": ObjectField("date", createable=True, updateable=True),
    "LastModifiedDate": ObjectField("datetime", createable=True, updateable=True),
    "Name": ObjectField("string", createable=True, updateable=True),
}


def _transform(field, value):
    return transform_record({field: value}, OBJECT_FIELDS)[field]


def test_a_date_becomes_a_date_string():
    """A Date field takes the date alone."""
    assert _transform("Birthdate", datetime.date(2026, 1, 2)) == "2026-01-02"


def test_a_datetime_becomes_iso_8601():
    """ISO 8601 requires a T, which `str` on a datetime does not give."""
    value = datetime.datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)

    assert _transform("LastModifiedDate", value) == "2026-01-02T03:04:05.678901+00:00"


def test_a_datetime_keeps_its_offset():
    """An offset that is not UTC survives, because Salesforce reads it."""
    value = datetime.datetime(
        2026,
        1,
        2,
        3,
        4,
        5,
        tzinfo=datetime.timezone(datetime.timedelta(hours=-5)),
    )

    assert _transform("LastModifiedDate", value) == "2026-01-02T03:04:05-05:00"


def test_a_whole_second_carries_no_fraction():
    """Salesforce accepts a timestamp with no fractional part."""
    value = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    assert _transform("LastModifiedDate", value) == "2026-01-02T03:04:05+00:00"


def test_a_datetime_in_a_date_field_keeps_its_time():
    """Salesforce takes the literal date part of a timestamp for a Date field."""
    value = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)

    assert _transform("Birthdate", value) == "2026-01-02T03:04:05+00:00"


@pytest.mark.parametrize("value", ["plain", 42, True, 1.5])
def test_a_value_of_another_type_passes_through(value):
    """Only a date-like value needs formatting."""
    assert _transform("Name", value) == value


def test_a_date_like_string_passes_through():
    """A tap that declares no format leaves the value a string, and it loads."""
    assert _transform("Birthdate", "2026-01-02") == "2026-01-02"


def test_none_passes_through():
    """A null stays null, so Salesforce clears the field."""
    assert _transform("LastModifiedDate", None) is None


def test_a_field_absent_from_the_object_passes_through():
    """Salesforce owns the schema, so do not guess at a field it did not describe."""
    assert transform_record({"Nope": "x"}, OBJECT_FIELDS) == {"Nope": "x"}


def test_every_field_is_returned():
    """The transform must not drop a field it had no work to do on."""
    record = {
        "Birthdate": datetime.date(2026, 1, 2),
        "Name": "Acme",
        "LastModifiedDate": None,
    }

    assert set(transform_record(record, OBJECT_FIELDS)) == set(record)
