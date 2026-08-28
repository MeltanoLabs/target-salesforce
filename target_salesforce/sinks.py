"""Salesforce target sink class, which handles writing streams."""

from dataclasses import asdict
from typing import ClassVar

from simple_salesforce import Salesforce, bulk, exceptions
from singer_sdk.plugin_base import PluginBase
from singer_sdk.sinks import BatchSink

from target_salesforce.session_credentials import SalesforceAuth, parse_credentials
from target_salesforce.utils.exceptions import (
    InvalidStreamSchemaError,
    SalesforceApiError,
)
from target_salesforce.utils.transformation import transform_record
from target_salesforce.utils.validation import ObjectField, validate_schema_field


class SalesforceSink(BatchSink):
    """Salesforce target sink class."""

    max_size = 5000
    valid_actions: ClassVar[list[str]] = [
        "insert",
        "update",
        "delete",
        "hard_delete",
        "upsert",
    ]
    include_sdc_metadata_properties = False

    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: dict,
        key_properties: list[str] | None,
    ) -> None:
        """Initialize the sink and check the schema against the Salesforce object."""
        super().__init__(target, stream_name, schema, key_properties)
        self.target = target
        self._sf_client = None
        self._batched_records: list[dict]
        self._object_fields: dict[str, ObjectField] | None = None
        self._validate_schema_against_object()

    @property
    def sf_client(self):
        """Return the Salesforce client, and open a session if there is none."""
        if self._sf_client:
            return self._sf_client
        return self._new_session()

    @property
    def object_fields(self) -> dict[str, ObjectField]:
        """Return the fields of the Salesforce object, keyed by field name."""
        if self._object_fields:
            return self._object_fields
        object_fields = {}

        stream_object = getattr(self.sf_client, self.stream_name)
        for field in stream_object.describe().get("fields"):
            object_fields[field.get("name")] = ObjectField(
                field.get("type"),
                field.get("createable"),
                field.get("updateable"),
            )

        self._object_fields = object_fields
        return self._object_fields

    def _validate_schema_against_object(self):
        try:
            for field_name in self.schema.get("properties"):
                validate_schema_field(
                    field_name,
                    self.object_fields,
                    self.config.get("action"),
                    self.stream_name,
                )
        except InvalidStreamSchemaError as e:
            msg = (
                f"The incoming schema is incompatible with your "
                f"{self.stream_name} object"
            )
            raise InvalidStreamSchemaError(msg) from e

    def _new_session(self):
        session_creds = SalesforceAuth.from_credentials(
            parse_credentials(self.target.config),
            domain=self.target.config["domain"],
        ).login()
        self._sf_client = Salesforce(**asdict(session_creds))
        return self._sf_client

    def start_batch(self, context: dict) -> None:
        """Start a new batch of records."""
        self.logger.info("Starting new batch")
        self._batched_records = []

    def process_record(self, record: dict, context: dict) -> None:
        """Transform and batch record."""
        processed_record = transform_record(record, self.object_fields)

        self._batched_records.append(processed_record)

    def process_batch(self, context: dict) -> None:
        """Write out any prepped records and return once fully written."""
        sf_object: bulk.SFBulkType = getattr(self.sf_client.bulk, self.stream_name)

        results = self._process_batch_by_action(
            sf_object, self.config.get("action"), self._batched_records
        )

        self._validate_batch_result(
            results, self.config.get("action"), self._batched_records
        )

        # Refresh session to avoid timeouts.
        self._new_session()

    def _process_batch_by_action(
        self, sf_object: bulk.SFBulkType, action, batched_data
    ):
        """Handle upsert records different method."""
        sf_object_action = getattr(sf_object, action)

        try:
            if action == "upsert":
                results = sf_object_action(batched_data, "Id")
            else:
                results = sf_object_action(batched_data)
        except exceptions.SalesforceMalformedRequest:
            self.logger.exception(
                "Data in %s %s batch does not conform to target SF %s Object",
                action,
                self.stream_name,
                self.stream_name,
            )
            raise

        return results

    def _validate_batch_result(self, results: list[dict], action, batched_records):
        records_failed = 0
        records_processed = 0

        for i, result in enumerate(results):
            if result.get("success"):
                records_processed += 1
            else:
                records_failed += 1
                self.logger.error(
                    "Failed %s to %s. Error: %s. Record %s",
                    action,
                    self.stream_name,
                    result.get("errors"),
                    batched_records[i],
                )

        self.logger.info(
            "%s %s/%s to %s.",
            action,
            records_processed,
            len(results),
            self.stream_name,
        )

        if records_failed > 0 and not self.config.get("allow_failures"):
            msg = (
                f"{records_failed} error(s) in {action} batch commit to "
                f"{self.stream_name}."
            )
            raise SalesforceApiError(msg)
