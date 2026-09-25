"""Tests for the Salesforce sink."""

import csv
import logging
import pathlib
import tempfile
from collections.abc import Callable

import pytest
from simple_salesforce import bulk2
from singer_sdk import metrics

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


def test_the_failed_records_csv_goes_to_a_file_not_the_log(
    caplog, monkeypatch, tmp_path
):
    """The log names a file that holds the CSV, and does not hold the CSV."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    failed_csv = '"sf__Id","sf__Error","Id"\n"","REQUIRED_FIELD_MISSING::Name","001"\n'

    class _FailedRecordsBulkType:
        def get_failed_records(self, job_id: str) -> str:  # noqa: ARG002
            return failed_csv

    sink = _make_sink("public-Product2")

    with caplog.at_level(logging.ERROR):
        sink._log_failed_records(_FailedRecordsBulkType(), "750xx", "update")  # noqa: SLF001

    (message,) = [record.getMessage() for record in caplog.records]
    dump = pathlib.Path(message.rsplit(" ", 1)[1])
    assert message.startswith("Failed records for update Product2 (job 750xx): ")
    assert dump.parent == tmp_path
    assert dump.name.startswith("target-salesforce-Product2-750xx-")
    assert dump.read_text() == failed_csv
    assert "REQUIRED_FIELD_MISSING" not in message


def test_record_count_counts_only_the_records_that_salesforce_loads(
    caplog, monkeypatch
):
    """Each batch logs the loaded records, not the records that the target reads."""
    sink = _make_sink("public-Account", {"allow_failures": True})
    monkeypatch.setattr(sink, "_log_failed_records", lambda *_: None)
    job = {
        "job_id": "750xx",
        "numberRecordsTotal": 5000,
        "numberRecordsProcessed": 5000,
        "numberRecordsFailed": 438,
    }

    with caplog.at_level(logging.INFO, logger=metrics.METRICS_LOGGER_NAME):
        for _ in range(5000):
            sink.record_counter_metric.increment()
        sink._validate_batch_result(None, [job], "update")  # noqa: SLF001

    (point,) = [
        record.args[0] for record in caplog.records if record.msg == "METRIC: %s"
    ]
    assert point.metric == metrics.Metric.RECORD_COUNT
    assert point.value == job["numberRecordsProcessed"] - job["numberRecordsFailed"]
