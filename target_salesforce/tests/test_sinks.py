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


class _FailedRecordsBulkType:
    """Stand-in for a Bulk 2.0 object that returns one failed-records CSV."""

    def __init__(self, failed_csv: str) -> None:
        self.failed_csv = failed_csv

    def get_failed_records(self, job_id: str) -> str:  # noqa: ARG002
        return self.failed_csv


@pytest.fixture
def tempdir(monkeypatch, tmp_path):
    """Keep the temporary files of the sink inside the directory of the test."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _log_failed_records(caplog, failed_csv: str, action: str = "update") -> str:
    """Log the failures of job 750xx to Product2, and return the one error line."""
    sink = _make_sink("public-Product2")

    with caplog.at_level(logging.ERROR):
        sink._log_failed_records(  # noqa: SLF001
            _FailedRecordsBulkType(failed_csv), "750xx", action
        )

    (message,) = [record.getMessage() for record in caplog.records]
    return message


@pytest.mark.usefixtures("tempdir")
def test_failed_records_are_counted_by_status_code(caplog):
    """The most common code comes first, with the id and message of its first record.

    The message loses its trailing fields part, and a long message is cut short.
    """
    lock = (
        "UNABLE_TO_LOCK_ROW:unable to obtain exclusive access to this record "
        "or 200 records: 001xx0000000001AAA:--"
    )
    rows = [f'"","{lock}","a3b{i}"' for i in range(7)]
    rows += ['"","INVALID_CROSS_REFERENCE_KEY:invalid cross reference id:--","a3bZ"']
    failed_csv = '"sf__Id","sf__Error","id"\n' + "\n".join(rows) + "\n"

    message = _log_failed_records(caplog, failed_csv)

    assert message.startswith(
        "Failed records for update Product2 (job 750xx): "
        "7 UNABLE_TO_LOCK_ROW (e.g. a3b0: unable to obtain exclusive access to ...); "
        "1 INVALID_CROSS_REFERENCE_KEY (e.g. a3bZ: invalid cross reference id)."
    )


def test_the_failed_records_csv_goes_to_a_temporary_file(caplog, tempdir):
    """The error line ends with the path of a file that holds the CSV unchanged.

    Salesforce ends each line with CRLF, and a quoted value can hold a lone
    carriage return. The file must keep both exactly as they arrived.
    """
    failed_csv = (
        '"sf__Id","sf__Error","Id","Street"\r\n'
        '"","REQUIRED_FIELD_MISSING::Name","a3b","Unit 1\rLondon"\r\n'
    )

    message = _log_failed_records(caplog, failed_csv)

    dump = pathlib.Path(message.rsplit(". CSV: ", 1)[1])
    assert dump.parent == tempdir
    assert dump.name.startswith("target-salesforce-")
    assert dump.read_bytes() == failed_csv.encode()


@pytest.mark.usefixtures("tempdir")
def test_a_failed_insert_is_counted_without_ids(caplog):
    """An insert sends no id, so the example holds the message alone."""
    failed_csv = (
        '"sf__Id","sf__Error","Name"\n'
        '"","REQUIRED_FIELD_MISSING:Required fields are missing: [Name]:Name",""\n'
    )

    message = _log_failed_records(caplog, failed_csv, action="insert")

    assert (
        "(job 750xx): 1 REQUIRED_FIELD_MISSING "
        "(e.g. Required fields are missing: [Name]). CSV: "
    ) in message


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
