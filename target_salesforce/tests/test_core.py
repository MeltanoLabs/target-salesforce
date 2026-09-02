"""Tests standard target features using the built-in SDK tests library."""

import os

import pytest
from singer_sdk.testing import get_target_test_class

from target_salesforce.target import TargetSalesforce

REQUIRED_SETTINGS = ("username", "password", "security_token")

SAMPLE_CONFIG = {
    "username": os.environ.get("TARGET_SALESFORCE_USERNAME"),
    "password": os.environ.get("TARGET_SALESFORCE_PASSWORD"),
    "security_token": os.environ.get("TARGET_SALESFORCE_SECURITY_TOKEN"),
    "domain": os.environ.get("TARGET_SALESFORCE_DOMAIN", "test"),
}

# The standard suite writes records to a Salesforce object over the API, so it
# needs credentials for a sandbox org. Skip the suite when they are absent.
pytestmark = pytest.mark.skipif(
    not all(SAMPLE_CONFIG[setting] for setting in REQUIRED_SETTINGS),
    reason="No Salesforce credentials in the environment",
)


# Run standard built-in target tests from the SDK:
TestTargetSalesforce = get_target_test_class(
    target_class=TargetSalesforce,
    config=SAMPLE_CONFIG,
)
