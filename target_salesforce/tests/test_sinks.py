"""Tests for the Salesforce sink."""

import csv
import logging
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from simple_salesforce import bulk2

from target_salesforce.sinks import SalesforceSink
from target_salesforce.target import TargetSalesforce


def _make_sink(stream_name: str, config: dict | None = None) -> SalesforceSink:
    target = TargetSalesforce(config=config or {}, validate_config=False)
    return SalesforceSink(
        target,
        stream_name=stream_name,
        schema={"properties": {}},
        key_properties=[],
    )


def test_object_name_strips_schema_prefix():
    """A schema-prefixed stream resolves to the final hyphen-separated part."""
    sink = _make_sink("public-Account")
    assert sink.object_name == "Account"


def test_object_name_without_prefix_is_unchanged():
    """A stream with no hyphen resolves to itself."""
    sink = _make_sink("Account")
    assert sink.object_name == "Account"


def test_object_name_keeps_raw_stream_name_when_configured():
    """use_raw_stream_names keeps the whole stream name as the object name."""
    sink = _make_sink("public-Account", {"use_raw_stream_names": True})
    assert sink.object_name == "public-Account"


class _RecordingBulkType:
    """Stand-in for a Bulk 2.0 object that records the ingest arguments."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __getattr__(self, action: str) -> Callable:
        def ingest(**kwargs):
            self.calls.append((action, kwargs))
            return []

        return ingest


@pytest.mark.parametrize(
    "action",
    ["insert", "update", "delete", "hard_delete", "upsert"],
)
def test_every_action_requests_the_crlf_line_ending(action):
    """Each ingest method asks for CRLF, not the LF that the library defaults to."""
    sink = _make_sink("public-Account")
    sf_object = _RecordingBulkType()

    sink._process_batch_by_action(sf_object, action, [{"Id": "001"}])  # noqa: SLF001

    ((called_action, kwargs),) = sf_object.calls
    assert called_action == action
    assert kwargs["line_ending"] is bulk2.LineEnding.CRLF


def test_crlf_quotes_a_lone_carriage_return():
    """A value that holds a lone carriage return survives the CSV round trip."""
    records = [{"Id": "001", "BillingStreet": "Unit 1\rLondon"}]

    data = bulk2._convert_dict_to_csv(records, line_ending=bulk2.LineEnding.CRLF)  # noqa: SLF001
    chunks = list(
        bulk2._split_csv(records=data, line_ending=bulk2.LineEnding.CRLF)  # noqa: SLF001
    )

    assert [count for count, _ in chunks] == [1]
    assert '"Unit 1\rLondon"' in chunks[0][1]


def test_the_library_default_rejects_a_lone_carriage_return():
    """Pin the upstream defect that the CRLF line ending works around.

    The CSV writer quotes a value only when it holds a character of the line
    terminator, so under LF it emits a lone carriage return bare. The reader
    treats that carriage return as the end of a record whatever the terminator
    is, and so rejects the text that the writer just produced.
    """
    records = [{"Id": "001", "BillingStreet": "Unit 1\rLondon"}]

    data = bulk2._convert_dict_to_csv(records)  # noqa: SLF001

    with pytest.raises(csv.Error, match="new-line character seen in unquoted field"):
        list(bulk2._split_csv(records=data))  # noqa: SLF001


class _FailedRecordsBulkType:
    """Stand-in for a Bulk 2.0 object that returns one failed-records CSV."""

    def __init__(self, failed_csv: str) -> None:
        self.failed_csv = failed_csv

    def get_failed_records(self, job_id: str) -> str:  # noqa: ARG002
        return self.failed_csv


def _log_failed_records(caplog, failed_csv: str, action: str = "update") -> str:
    """Log the failures of job 750xx to Product2, and return the one error line."""
    sink = _make_sink("public-Product2")
    sink._sf_client = SimpleNamespace(  # noqa: SLF001
        bulk2_url="https://example.my.salesforce.com/services/data/v59.0/jobs/"
    )

    with caplog.at_level(logging.ERROR):
        sink._log_failed_records(  # noqa: SLF001
            _FailedRecordsBulkType(failed_csv), "750xx", action
        )

    (message,) = [record.getMessage() for record in caplog.records]
    return message


def test_failed_records_are_counted_by_status_code(caplog):
    """The most common code comes first, and each code names at most five ids."""
    rows = [f'"","UNABLE_TO_LOCK_ROW:locked: 001x","a3b{i}"' for i in range(7)]
    rows += ['"","INVALID_CROSS_REFERENCE_KEY:invalid cross reference id:--","a3bZ"']
    failed_csv = '"sf__Id","sf__Error","id"\n' + "\n".join(rows) + "\n"

    message = _log_failed_records(caplog, failed_csv)

    assert message.startswith(
        "Failed records for update Product2 (job 750xx): "
        "7 UNABLE_TO_LOCK_ROW (a3b0, a3b1, a3b2, a3b3, a3b4); "
        "1 INVALID_CROSS_REFERENCE_KEY (a3bZ)."
    )


def test_the_log_links_the_csv_that_salesforce_keeps(caplog):
    """The error line ends with the REST URL of the job's failed results."""
    failed_csv = '"sf__Id","sf__Error","Id"\n"","REQUIRED_FIELD_MISSING::Name","a3b"\n'

    message = _log_failed_records(caplog, failed_csv)

    assert message.endswith(
        ". CSV: https://example.my.salesforce.com/services/data/v59.0"
        "/jobs/ingest/750xx/failedResults/"
    )


def test_a_failed_insert_is_counted_without_ids(caplog):
    """An insert sends no id, so the line holds the count alone."""
    failed_csv = '"sf__Id","sf__Error","Name"\n"","REQUIRED_FIELD_MISSING::Name",""\n'

    message = _log_failed_records(caplog, failed_csv, action="insert")

    assert "(job 750xx): 1 REQUIRED_FIELD_MISSING. CSV: " in message
