"""Validation of an incoming stream schema against a Salesforce object.

The checks are:

1. The field exists in the Salesforce object, excluding `_sdc` metadata.
2. If the config action is update, that the field can be updated.
3. If the config action is insert, that the field can be created.
4. If the config action is upsert, that the field can be created and updated.
"""

from typing import NamedTuple

from target_salesforce.utils.exceptions import InvalidStreamSchemaError


class ObjectField(NamedTuple):
    """A field of a Salesforce object, as the describe call reports it."""

    type: str
    createable: bool
    updateable: bool


def validate_schema_field(
    field_name: str,
    object_fields: dict[str, ObjectField],
    action: str,
    stream_name: str,
):
    """Validate one incoming schema field against the Salesforce object."""
    sf_field: ObjectField | None = object_fields.get(field_name)

    if field_name.startswith("_sdc_"):
        return

    if field_name == "Id":
        if action == "insert":
            msg = "Id is not createable and should not be included on insert"
            raise InvalidStreamSchemaError(msg)
        return

    if not sf_field:
        msg = f"{field_name} does not exist in your {stream_name} Object"
        raise InvalidStreamSchemaError(msg)

    if action in ("update", "upsert") and not sf_field.updateable:
        msg = (
            f"{field_name} is not updatable for your {stream_name} Object, "
            f"invalid for {action} action"
        )
        raise InvalidStreamSchemaError(msg)

    if action in ("insert", "upsert") and not sf_field.createable:
        msg = (
            f"{field_name} is not creatable for your {stream_name} Object, "
            f"invalid for {action} action"
        )
        raise InvalidStreamSchemaError(msg)

    if action in ("delete", "hard_delete"):
        msg = f"Schema for the {action} action should only include Id"
        raise InvalidStreamSchemaError(msg)
