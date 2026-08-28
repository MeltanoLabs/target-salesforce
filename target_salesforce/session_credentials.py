"""Salesforce login flows and session handling."""

import abc
import logging
from dataclasses import dataclass
from typing import NamedTuple

import requests
from simple_salesforce import SalesforceLogin

from target_salesforce.utils.exceptions import (
    InvalidCredentialsError,
    SalesforceLoginError,
)

LOGGER = logging.getLogger(__name__)

# No record can be written until the login returns, so a login that hangs
# stalls the whole run.
LOGIN_TIMEOUT_SECONDS = 30


class OAuthCredentials(NamedTuple):
    """Credentials for the OAuth refresh token flow."""

    client_id: str
    client_secret: str
    refresh_token: str


class PasswordCredentials(NamedTuple):
    """Credentials for the username and password flow."""

    username: str
    password: str
    security_token: str


@dataclass
class Session:
    """An authenticated Salesforce session."""

    session_id: str
    instance: str | None = None
    instance_url: str | None = None


def parse_credentials(config: dict) -> OAuthCredentials | PasswordCredentials:
    """Return the credentials that the config holds a complete set of."""
    for cls in reversed((OAuthCredentials, PasswordCredentials)):
        creds = cls(*(config.get(key) for key in cls._fields))
        if all(creds):
            return creds

    msg = (
        "Cannot create credentials from config. Target supports OAuth and "
        "Password authentication."
    )
    raise InvalidCredentialsError(msg)


class SalesforceAuth(metaclass=abc.ABCMeta):
    """Base class for the Salesforce login flows."""

    def __init__(self, credentials, domain) -> None:
        """Hold the credentials and the domain to login against."""
        self.domain = domain
        self._credentials = credentials

    @abc.abstractmethod
    def login(self) -> Session:
        """Attempt to login and return Session info."""

    @classmethod
    def from_credentials(cls, credentials, **kwargs) -> "SalesforceAuth":
        """Return the login flow that matches the credentials."""
        if isinstance(credentials, OAuthCredentials):
            return SalesforceAuthOAuth(credentials, **kwargs)

        if isinstance(credentials, PasswordCredentials):
            return SalesforceAuthPassword(credentials, **kwargs)

        msg = "Invalid credentials"
        raise InvalidCredentialsError(msg)


class SalesforceAuthOAuth(SalesforceAuth):
    """Login with an OAuth refresh token."""

    @property
    def _login_body(self):
        return {"grant_type": "refresh_token", **self._credentials._asdict()}

    @property
    def _login_url(self):
        return f"https://{self.domain}.salesforce.com/services/oauth2/token"

    def login(self):
        """Attempt to login and return Session info."""
        # `requests.post` can raise before it binds a response, and a response
        # that carries an error status is falsy. Test against None so that the
        # body reaches the caller for every failure that produced one.
        resp = None

        try:
            LOGGER.info("Attempting login via OAuth2")

            resp = requests.post(
                self._login_url,
                data=self._login_body,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=LOGIN_TIMEOUT_SECONDS,
            )

            resp.raise_for_status()
            auth = resp.json()

            LOGGER.info("OAuth2 login successful")
            return Session(auth["access_token"], instance_url=auth["instance_url"])
        except Exception as e:
            error_message = str(e)
            if resp is not None:
                error_message = (
                    error_message + f", Response from Salesforce: {resp.text}"
                )
            raise SalesforceLoginError(error_message) from e


class SalesforceAuthPassword(SalesforceAuth):
    """Login with a username, a password, and a security token."""

    def login(self):
        """Attempt to login and return Session info."""
        session_id, instance = SalesforceLogin(
            domain=self.domain, **self._credentials._asdict()
        )
        return Session(session_id, instance=instance)
