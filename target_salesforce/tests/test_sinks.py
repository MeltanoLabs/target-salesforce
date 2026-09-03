"""Tests for the Salesforce sink."""

import logging
from unittest import mock

import pytest

from target_salesforce.sinks import SalesforceSink
from target_salesforce.utils.exceptions import SalesforceApiError
from target_salesforce.utils.validation import ObjectField

FAILED_CSV = '"sf__Error","Id"\n"REQUIRED_FIELD_MISSING","001x"'


def _sink(describe_fields=None):
    """Build a sink without its constructor, which opens a Salesforce session."""
    sink = SalesforceSink.__new__(SalesforceSink)
    sink.stream_name = "Account"
    sink.logger = logging.getLogger("test")
    sink._object_fields = None  # noqa: SLF001
    sink._sf_client = mock.Mock()  # noqa: SLF001
    sink._sf_client.Account.describe.return_value = {  # noqa: SLF001
        "fields": describe_fields or [],
    }
    return sink


def _jobs(*failed_counts):
    """Return one Bulk 2.0 job summary per chunk, each covering 50 records."""
    return [
        {
            "job_id": f"job{i}",
            "numberRecordsTotal": 50,
            "numberRecordsProcessed": 50,
            "numberRecordsFailed": failed,
        }
        for i, failed in enumerate(failed_counts)
    ]


def test_object_fields_reads_the_describe_call():
    """Each described field becomes an ObjectField, keyed by its name."""
    sink = _sink(
        [
            {"name": "Name", "type": "string", "createable": True, "updateable": True},
            {"name": "Id", "type": "id", "createable": False, "updateable": False},
        ],
    )

    assert sink.object_fields == {
        "Name": ObjectField("string", createable=True, updateable=True),
        "Id": ObjectField("id", createable=False, updateable=False),
    }


def test_object_fields_describes_the_object_only_once():
    """The describe call costs an API round trip, so its result is kept."""
    sink = _sink(
        [{"name": "Id", "type": "id", "createable": False, "updateable": False}],
    )

    first = sink.object_fields
    second = sink.object_fields

    assert first == second
    assert sink._sf_client.Account.describe.call_count == 1  # noqa: SLF001


def test_a_clean_batch_raises_nothing():
    """Every record landed, so there is nothing to fetch or report."""
    sink = _sink()
    sf_object = mock.Mock()

    with mock.patch.object(SalesforceSink, "config", {"allow_failures": False}):
        sink._validate_batch_result(sf_object, _jobs(0, 0), "update")  # noqa: SLF001

    sf_object.get_failed_records.assert_not_called()


def test_a_failed_record_raises_and_names_the_count():
    """A failure stops the run unless the config allows it through."""
    sink = _sink()
    sf_object = mock.Mock()
    sf_object.get_failed_records.return_value = FAILED_CSV

    with (
        mock.patch.object(SalesforceSink, "config", {"allow_failures": False}),
        pytest.raises(SalesforceApiError, match="3 error"),
    ):
        sink._validate_batch_result(sf_object, _jobs(0, 3), "update")  # noqa: SLF001


def test_allow_failures_lets_a_failed_record_through():
    """The config opts out of the raise."""
    sink = _sink()
    sf_object = mock.Mock()
    sf_object.get_failed_records.return_value = FAILED_CSV

    with mock.patch.object(SalesforceSink, "config", {"allow_failures": True}):
        sink._validate_batch_result(sf_object, _jobs(0, 3), "update")  # noqa: SLF001


def test_only_a_failing_chunk_is_fetched():
    """Bulk 2.0 keeps a CSV per job, and a clean job has nothing to read."""
    sink = _sink()
    sf_object = mock.Mock()
    sf_object.get_failed_records.return_value = FAILED_CSV

    with mock.patch.object(SalesforceSink, "config", {"allow_failures": True}):
        sink._validate_batch_result(sf_object, _jobs(0, 2, 0, 1), "update")  # noqa: SLF001

    fetched = [call.args[0] for call in sf_object.get_failed_records.call_args_list]
    assert fetched == ["job1", "job3"]


def test_an_unreadable_csv_does_not_hide_the_batch_failure():
    """The diagnostic fetch is a second call, and it must not mask the first."""
    sink = _sink()
    sf_object = mock.Mock()
    sf_object.get_failed_records.side_effect = RuntimeError("403 forbidden")

    with (
        mock.patch.object(SalesforceSink, "config", {"allow_failures": False}),
        pytest.raises(SalesforceApiError, match="3 error"),
    ):
        sink._validate_batch_result(sf_object, _jobs(3), "update")  # noqa: SLF001
