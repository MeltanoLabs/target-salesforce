"""Tests standard target features using the built-in SDK tests library."""

from singer_sdk.testing import get_target_test_class
from singer_sdk.testing.suites import SingerTestSuite, target_tests

from target_salesforce.target import TargetSalesforce

# Most of the standard suite writes streams named `test_array_data`,
# `TestCamelcase`, and so on. This target requires every stream to name an
# existing Salesforce object, and the sink constructor calls describe() on it,
# so those tests cannot pass against any org. Keep the tests that reject their
# input, or never open a session, because those exercise the target itself.
STREAMLESS_TESTS = frozenset(
    {
        "cli_prints",
        "invalid_schema",
        "record_before_schema",
    },
)

streamless_suite = SingerTestSuite(
    kind="target",
    tests=[test for test in target_tests.tests if test.name in STREAMLESS_TESTS],
)


# Run the built-in target tests that do not need a Salesforce object:
TestTargetSalesforce = get_target_test_class(
    target_class=TargetSalesforce,
    config={},
    custom_suites=[streamless_suite],
    include_target_tests=False,
)
