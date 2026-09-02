"""Tests for the Salesforce credential parsing and login flows."""

from unittest import mock

import pytest
import requests

from target_salesforce.session_credentials import (
    OAuthCredentials,
    PasswordCredentials,
    SalesforceAuth,
    parse_credentials,
)
from target_salesforce.utils.exceptions import (
    InvalidCredentialsError,
    SalesforceLoginError,
)

OAUTH_CONFIG = {
    "client_id": "an-id",
    "client_secret": "a-secret",
    "refresh_token": "a-token",
}
PASSWORD_CONFIG = {
    "username": "a-user",
    "password": "a-password",
    "security_token": "a-token",
}


def _response(status_code: int, body: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode()  # noqa: SLF001
    response.url = "https://login.salesforce.com/services/oauth2/token"
    return response


def test_parse_credentials_reads_oauth():
    """A complete OAuth set in the config becomes OAuth credentials."""
    assert parse_credentials(OAUTH_CONFIG) == OAuthCredentials(**OAUTH_CONFIG)


def test_parse_credentials_reads_password():
    """A complete password set in the config becomes password credentials."""
    expected = PasswordCredentials(**PASSWORD_CONFIG)
    assert parse_credentials(PASSWORD_CONFIG) == expected


def test_parse_credentials_rejects_a_partial_set():
    """A config that holds neither complete set is an error."""
    with pytest.raises(InvalidCredentialsError):
        parse_credentials({"username": "a-user"})


def test_oauth_login_reports_the_salesforce_response_body():
    """A failed login must name the reason that Salesforce gave for it."""
    auth = SalesforceAuth.from_credentials(
        OAuthCredentials(**OAUTH_CONFIG),
        domain="login",
    )
    body = (
        '{"error":"invalid_grant","error_description":"expired access/refresh token"}'
    )

    with (
        mock.patch.object(requests, "post", return_value=_response(400, body)),
        pytest.raises(SalesforceLoginError, match="expired access/refresh token"),
    ):
        auth.login()


def test_oauth_login_reports_a_request_that_never_answered():
    """A login that fails before a response must not mask the original error."""
    auth = SalesforceAuth.from_credentials(
        OAuthCredentials(**OAUTH_CONFIG),
        domain="login",
    )

    with (
        mock.patch.object(
            requests,
            "post",
            side_effect=requests.ConnectionError("no route to host"),
        ),
        pytest.raises(SalesforceLoginError, match="no route to host"),
    ):
        auth.login()
