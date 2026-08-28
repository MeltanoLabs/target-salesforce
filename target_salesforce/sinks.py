"""Salesforce target sink class, which handles writing streams."""

from dataclasses import asdict
from typing import ClassVar

from simple_salesforce import Salesforce, bulk2, exceptions
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
        sf_object: bulk2.SFBulk2Type = getattr(self.sf_client.bulk2, self.stream_name)

        results = self._process_batch_by_action(
            sf_object, self.config.get("action"), self._batched_records
        )

        self._validate_batch_result(sf_object, results, self.config.get("action"))

        # Refresh session to avoid timeouts.
        self._new_session()

    def _process_batch_by_action(
        self, sf_object: bulk2.SFBulk2Type, action, batched_data
    ):
        """Dispatch the batch to the matching Bulk 2.0 ingest method.

        Bulk 2.0 ingest methods take ``records=`` as a keyword argument and
        return one summary dict per chunk, not per-record results.
        """
        sf_object_action = getattr(sf_object, action)

        try:
            if action == "upsert":
                return sf_object_action(records=batched_data, external_id_field="Id")
            return sf_object_action(records=batched_data)
        except exceptions.SalesforceMalformedRequest:
            self.logger.exception(
                "Data in %s %s batch does not conform to target SF %s Object",
                action,
                self.stream_name,
                self.stream_name,
            )
            raise

    def _validate_batch_result(
        self, sf_object: bulk2.SFBulk2Type, results: list[dict], action
    ):
        total_processed = 0
        total_failed = 0
        total_records = 0

        for job in results:
            total_records += int(job.get("numberRecordsTotal", 0))
            total_processed += int(job.get("numberRecordsProcessed", 0))
            failed = int(job.get("numberRecordsFailed", 0))
            total_failed += failed

            if failed > 0:
                self._log_failed_records(sf_object, job.get("job_id"), action)

        successful = total_processed - total_failed
        self.logger.info(
            "%s %s/%s to %s.",
            action,
            successful,
            total_records,
            self.stream_name,
        )

        if total_failed > 0 and not self.config.get("allow_failures"):
            msg = (
                f"{total_failed} error(s) in {action} batch commit to "
                f"{self.stream_name}."
            )
            raise SalesforceApiError(msg)

    def _log_failed_records(self, sf_object: bulk2.SFBulk2Type, job_id, action) -> None:
        """Log the failed-records CSV that Bulk 2.0 keeps for one job.

        Bulk 2.0 reports a count per chunk rather than a result per record, so
        the CSV is the only place that names which record failed and why. The
        fetch is a second API call, and a failure to read it must not hide the
        batch failure that prompted it.
        """
        try:
            failed_csv = sf_object.get_failed_records(job_id)
        except Exception:
            self.logger.exception("Could not fetch failed records for job %s", job_id)
        else:
            self.logger.error(
                "Failed records for %s %s (job %s):\n%s",
                action,
                self.stream_name,
                job_id,
                failed_csv,
            )
