"""The shape of a Salesforce object field, as the describe call reports it."""

from typing import NamedTuple


class ObjectField(NamedTuple):
    """A field of a Salesforce object, as the describe call reports it."""

    type: str
    createable: bool
    updateable: bool
