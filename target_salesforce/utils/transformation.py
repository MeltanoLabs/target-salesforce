"""Conversion of Python date and time values back into strings for Salesforce."""

import datetime

from target_salesforce.utils.validation import ObjectField

DATE_FORMAT = "%Y-%m-%d"


def transform_record(
    record: dict,
    object_fields: dict[str, ObjectField],
) -> dict:
    """Return the record with each date, datetime, and time value as a string.

    The SDK parses a date-like field into a Python object before the sink sees
    it. Salesforce is reached over a CSV upload, which renders whatever it is
    given with `str`, and that spells a datetime with a space rather than the
    `T` that ISO 8601 requires. Format these values here instead.
    """
    transformed_record = {}

    for field, value in record.items():
        sf_field = object_fields.get(field)

        if value is None or sf_field is None:
            transformed_record[field] = value
            continue

        transformed_record[field] = _format_value(value, sf_field.type)

    return transformed_record


def _format_value(value, sf_type: str):
    """Return one value as Salesforce spells its type, or unchanged."""
    # A datetime is also a date, so read the Salesforce type rather than the
    # Python one. strftime keeps a date field to its date even so.
    if sf_type == "date" and isinstance(value, datetime.date):
        return value.strftime(DATE_FORMAT)

    # Salesforce specifies three fractional digits. `isoformat` gives six by
    # default, and none at all when the microsecond is zero.
    if sf_type == "datetime" and isinstance(value, datetime.datetime):
        return value.isoformat(timespec="milliseconds")

    if sf_type == "time" and isinstance(value, datetime.time):
        return value.isoformat(timespec="milliseconds")

    return value
