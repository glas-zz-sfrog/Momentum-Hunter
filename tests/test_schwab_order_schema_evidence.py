from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from momentum_hunter.schwab_order_schema_evidence import (
    SCHWAB_ORDER_SCHEMA_EVIDENCE_VERSION,
    SchwabOrderSchemaEvidenceError,
    inspect_schwab_order_openapi,
    main,
)


class SchwabOrderSchemaEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.specification = _complete_specification()

    def inspect(self, payload: object | None = None):
        raw = json.dumps(
            self.specification if payload is None else payload,
            sort_keys=True,
        ).encode("utf-8")
        return inspect_schwab_order_openapi(raw)

    def test_complete_direct_schema_is_ready_and_nontransmitting(self) -> None:
        evidence = self.inspect()
        payload = evidence.to_dict()

        self.assertTrue(evidence.ready_for_canary_reconciliation)
        self.assertEqual((), evidence.findings)
        self.assertEqual(
            "/accounts/{accountHash}/orders",
            evidence.collection_path,
        )
        self.assertEqual(
            "/accounts/{accountHash}/orders/{orderId}",
            evidence.detail_path,
        )
        self.assertEqual(
            SCHWAB_ORDER_SCHEMA_EVIDENCE_VERSION,
            payload["schemaVersion"],
        )
        self.assertTrue(payload["inspectionOnly"])
        self.assertFalse(payload["networkAccessed"])
        self.assertFalse(payload["credentialsAccessed"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_resolves_local_refs_arrays_and_nested_order_leg_fields(self) -> None:
        evidence = self.inspect()

        self.assertIn("orderLegCollection[]", evidence.response_field_paths)
        self.assertIn(
            "orderLegCollection[].instrument.symbol",
            evidence.response_field_paths,
        )
        availability = {
            item.logical_field: item.availability
            for item in evidence.field_evidence
        }
        self.assertEqual("DIRECT", availability["symbol"])
        self.assertEqual("DIRECT", availability["side"])
        self.assertEqual("DIRECT", availability["filledQuantity"])

    def test_missing_identity_and_lifecycle_fields_fail_closed(self) -> None:
        incomplete = deepcopy(self.specification)
        properties = incomplete["components"]["schemas"]["Order"]["properties"]
        del properties["clientCommandId"]
        del properties["updatedAt"]
        del properties["remainingQuantity"]

        evidence = self.inspect(incomplete)

        self.assertFalse(evidence.ready_for_canary_reconciliation)
        self.assertIn(
            "Required reconciliation fields are unavailable: "
            "clientCommandId, updatedAt, remainingQuantity.",
            evidence.findings,
        )

    def test_missing_collection_or_detail_get_operation_is_reported(self) -> None:
        no_detail = deepcopy(self.specification)
        del no_detail["paths"]["/accounts/{accountHash}/orders/{orderId}"]
        detail_evidence = self.inspect(no_detail)
        self.assertIn(
            "A GET order-detail operation was not found.",
            detail_evidence.findings,
        )

        no_collection = deepcopy(self.specification)
        del no_collection["paths"]["/accounts/{accountHash}/orders"]
        collection_evidence = self.inspect(no_collection)
        self.assertIn(
            "A GET order-collection operation was not found.",
            collection_evidence.findings,
        )

    def test_non_get_order_operations_do_not_count(self) -> None:
        post_only = deepcopy(self.specification)
        path_item = post_only["paths"]["/accounts/{accountHash}/orders"]
        path_item["post"] = path_item.pop("get")

        evidence = self.inspect(post_only)

        self.assertIn(
            "A GET order-collection operation was not found.",
            evidence.findings,
        )
        self.assertFalse(evidence.ready_for_canary_reconciliation)

    def test_wrong_server_host_and_embedded_credentials_fail_validation(self) -> None:
        wrong_server = deepcopy(self.specification)
        wrong_server["servers"] = [
            {
                "url": (
                    "https://user:password@api.schwabapi.com/trader/v1"
                    "?token=SYNTHETIC#fragment"
                )
            }
        ]

        evidence = self.inspect(wrong_server)
        rendered = json.dumps(evidence.to_dict(), sort_keys=True)

        self.assertIn(
            "The specification does not declare Schwab's exact HTTPS API host.",
            evidence.findings,
        )
        self.assertNotIn("user", rendered)
        self.assertNotIn("password", rendered)
        self.assertNotIn("SYNTHETIC", rendered)

    def test_portal_envelope_is_sanitized_and_secret_values_are_not_returned(self) -> None:
        secret_value = "SYNTHETIC-SECRET-MUST-NOT-LEAK"
        envelope = {
            "id": "synthetic-product-id",
            "appKey": "SYNTHETIC-APP-KEY",
            "appSecret": secret_value,
            "specification": json.dumps(self.specification),
        }

        evidence = self.inspect(envelope)
        rendered = json.dumps(evidence.to_dict(), sort_keys=True)

        self.assertEqual(("appKey", "appSecret"), evidence.sensitive_envelope_fields)
        self.assertNotIn(secret_value, rendered)
        self.assertNotIn("SYNTHETIC-APP-KEY", rendered)
        self.assertFalse(evidence.ready_for_canary_reconciliation)
        self.assertIn(
            "The portal export envelope contains credential-shaped fields; "
            "only the nested specification may be retained.",
            evidence.findings,
        )

    def test_collection_and_detail_schema_mismatch_is_reported(self) -> None:
        mismatch = deepcopy(self.specification)
        mismatch["components"]["schemas"]["OrderListItem"] = deepcopy(
            mismatch["components"]["schemas"]["Order"]
        )
        del mismatch["components"]["schemas"]["OrderListItem"]["properties"][
            "filledQuantity"
        ]
        collection_schema = mismatch["paths"][
            "/accounts/{accountHash}/orders"
        ]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        collection_schema["items"]["$ref"] = (
            "#/components/schemas/OrderListItem"
        )

        evidence = self.inspect(mismatch)

        self.assertIn(
            "Order collection and detail response fields are inconsistent.",
            evidence.findings,
        )
        self.assertFalse(evidence.ready_for_canary_reconciliation)

    def test_invalid_json_non_object_and_missing_specification_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            SchwabOrderSchemaEvidenceError,
            "valid UTF-8 JSON",
        ):
            inspect_schwab_order_openapi(b"{")
        with self.assertRaisesRegex(
            SchwabOrderSchemaEvidenceError,
            "JSON object",
        ):
            inspect_schwab_order_openapi(b"[]")
        with self.assertRaisesRegex(
            SchwabOrderSchemaEvidenceError,
            "does not contain an OpenAPI specification",
        ):
            inspect_schwab_order_openapi(b'{"id":"missing"}')

    def test_external_and_broken_refs_are_rejected_without_network(self) -> None:
        external = deepcopy(self.specification)
        external["paths"]["/accounts/{accountHash}/orders"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["items"]["$ref"] = (
            "https://example.invalid/order.json"
        )
        with self.assertRaisesRegex(
            SchwabOrderSchemaEvidenceError,
            "Only local OpenAPI references",
        ):
            self.inspect(external)

        broken = deepcopy(self.specification)
        broken["paths"]["/accounts/{accountHash}/orders"]["get"][
            "responses"
        ]["200"]["content"]["application/json"]["schema"]["items"]["$ref"] = (
            "#/components/schemas/Missing"
        )
        with self.assertRaisesRegex(
            SchwabOrderSchemaEvidenceError,
            "could not be resolved",
        ):
            self.inspect(broken)

    def test_input_mapping_is_not_mutated(self) -> None:
        original = deepcopy(self.specification)

        self.inspect(self.specification)

        self.assertEqual(original, self.specification)

    def test_cli_reads_local_export_and_prints_only_sanitized_evidence(self) -> None:
        secret_value = "SYNTHETIC-SECRET-MUST-NOT-LEAK"
        envelope = {
            "appKey": "SYNTHETIC-APP-KEY",
            "appSecret": secret_value,
            "specification": json.dumps(self.specification),
        }
        with TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "official-export.json"
            export_path.write_text(json.dumps(envelope), encoding="utf-8")
            output = StringIO()
            errors = StringIO()

            with redirect_stdout(output), redirect_stderr(errors):
                exit_code = main([str(export_path)])

        self.assertEqual(0, exit_code)
        self.assertEqual("", errors.getvalue())
        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(
            ["appKey", "appSecret"],
            payload["sensitiveEnvelopeFields"],
        )
        self.assertNotIn(secret_value, rendered)
        self.assertNotIn("SYNTHETIC-APP-KEY", rendered)
        self.assertFalse(payload["readyForCanaryReconciliation"])
        self.assertFalse(payload["networkAccessed"])
        self.assertFalse(payload["brokerActionAllowed"])

    def test_cli_failure_is_sanitized_and_nontransmitting(self) -> None:
        output = StringIO()
        errors = StringIO()

        with redirect_stdout(output), redirect_stderr(errors):
            exit_code = main(["missing-openapi-file.json"])

        self.assertEqual(2, exit_code)
        self.assertEqual("", output.getvalue())
        payload = json.loads(errors.getvalue())
        self.assertEqual("BLOCKED", payload["status"])
        self.assertNotIn("missing-openapi-file.json", errors.getvalue())
        self.assertFalse(payload["networkAccessed"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["transmitting"])

    def test_module_has_no_provider_transport_or_file_write_surface(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "schwab_order_schema_evidence.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "import requests",
            "import httpx",
            "import socket",
            "urlopen(",
            ".post(",
            ".put(",
            ".delete(",
            "write_text(",
            "write_bytes(",
        ):
            self.assertNotIn(forbidden, source)


def _complete_specification() -> dict[str, object]:
    order_properties = {
        "orderId": {"type": "integer"},
        "clientCommandId": {"type": "string"},
        "status": {"type": "string"},
        "enteredTime": {"type": "string", "format": "date-time"},
        "updatedAt": {"type": "string", "format": "date-time"},
        "quantity": {"type": "number"},
        "filledQuantity": {"type": "number"},
        "remainingQuantity": {"type": "number"},
        "averageFillPrice": {"type": "number"},
        "orderType": {"type": "string"},
        "price": {"type": "number"},
        "orderLegCollection": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/OrderLeg"},
        },
    }
    success_detail = {
        "description": "Order detail",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Order"}
            }
        },
    }
    success_collection = {
        "description": "Orders",
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/Order"},
                }
            }
        },
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Synthetic Schwab Trader API schema fixture",
            "version": "1.0.0",
        },
        "servers": [{"url": "https://api.schwabapi.com/trader/v1"}],
        "paths": {
            "/accounts/{accountHash}/orders": {
                "get": {
                    "operationId": "getOrdersByPath",
                    "responses": {"200": success_collection},
                }
            },
            "/accounts/{accountHash}/orders/{orderId}": {
                "get": {
                    "operationId": "getOrderById",
                    "responses": {"200": success_detail},
                }
            },
        },
        "components": {
            "schemas": {
                "Order": {
                    "type": "object",
                    "properties": order_properties,
                },
                "OrderLeg": {
                    "type": "object",
                    "properties": {
                        "instruction": {"type": "string"},
                        "instrument": {
                            "$ref": "#/components/schemas/Instrument"
                        },
                    },
                },
                "Instrument": {
                    "type": "object",
                    "properties": {
                        "symbol": {"type": "string"},
                        "assetType": {"type": "string"},
                    },
                },
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
