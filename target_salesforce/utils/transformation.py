"""Conversion of Python datetimes back to strings, so a record is JSON serializable."""

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%LZ"


def transform_record(record: dict, object_fields: dict):
    """Return the record with each date and datetime value as a string."""
    transformed_record: dict = {}
    for field, value in record.items():
        if value is None:
            transformed_record[field] = value
            continue

        object_type = object_fields.get(field)
        if object_type == "date":
            transformed_record[field] = value.strftime(DATE_FORMAT)
        elif object_type == "datetime":
            transformed_record[field] = value.strftime(DATETIME_FORMAT)
        else:
            transformed_record[field] = value

    return transformed_record
