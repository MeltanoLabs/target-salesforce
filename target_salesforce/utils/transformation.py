"""Conversion of Python date and datetime values back into strings for Salesforce."""

import datetime

from target_salesforce.utils.validation import ObjectField


def transform_record(
    record: dict,
    object_fields: dict[str, ObjectField],
) -> dict:
    """Return the record with each date and datetime value as a string.

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
        # The SDK gives a date for a `date` schema and a datetime for a
        # `date-time` one, so the value already carries the precision that the
        # field needs. A value that is not date-like belongs to a stream whose
        # schema declared no format, and Salesforce parses it as it stands.
        elif sf_field.type in {"date", "datetime"} and isinstance(value, datetime.date):
            transformed_record[field] = value.isoformat()
        else:
            transformed_record[field] = value

    return transformed_record
