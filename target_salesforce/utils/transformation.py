"""Conversion of a record into the form that the Salesforce Bulk API takes.

A date and a datetime become a string, so the record is JSON serializable, and
each key becomes the field name as Salesforce spells it.
"""

DATE_FORMAT = "%Y-%m-%d"
DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%LZ"


def transform_record(record: dict, object_fields: dict):
    """Return the record with Salesforce's own field names and string dates.

    A tap decides how it spells a column, so the key is rewritten to the name
    that the describe call reports.
    """
    transformed_record: dict = {}
    for field, value in record.items():
        sf_field = object_fields.get(field.lower())
        name = sf_field.name if sf_field else field

        if value is None:
            transformed_record[name] = value
            continue

        if sf_field == "date":
            transformed_record[name] = value.strftime(DATE_FORMAT)
        elif sf_field == "datetime":
            transformed_record[name] = value.strftime(DATETIME_FORMAT)
        else:
            transformed_record[name] = value

    return transformed_record
