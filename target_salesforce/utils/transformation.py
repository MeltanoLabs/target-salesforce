"""Conversion of Python date and datetime values back into strings for Salesforce."""

import datetime

from target_salesforce.utils.validation import ObjectField

DATE_FORMAT = "%Y-%m-%d"


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
        # A datetime is also a date, so read the Salesforce type rather than
        # the Python one. strftime keeps a date field to its date even so.
        elif sf_field.type == "date" and isinstance(value, datetime.date):
            transformed_record[field] = value.strftime(DATE_FORMAT)
        elif sf_field.type == "datetime" and isinstance(value, datetime.datetime):
            transformed_record[field] = value.isoformat(timespec="milliseconds")
        else:
            transformed_record[field] = value

    return transformed_record
