"""Exceptions that the Salesforce target raises."""


class InvalidSalesforceActionError(Exception):
    """The configured action is not one that the target can perform."""


class InvalidStreamSchemaError(Exception):
    """The incoming stream schema does not fit the target Salesforce object."""


class SalesforceApiError(Exception):
    """The Salesforce API rejected a record or a batch."""


class InvalidCredentialsError(Exception):
    """The config does not hold a complete set of credentials."""


class SalesforceLoginError(Exception):
    """Salesforce refused the login attempt."""
