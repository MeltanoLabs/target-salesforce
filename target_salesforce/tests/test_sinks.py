"""Tests for the Salesforce sink."""

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
