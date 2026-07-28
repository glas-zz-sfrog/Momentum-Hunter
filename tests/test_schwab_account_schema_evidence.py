from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from io import StringIO
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from momentum_hunter.schwab_account_schema_evidence import (
    MAX_OPENAPI_EXPORT_BYTES,
    SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION,
    SchwabAccountSchemaEvidenceError,
    inspect_schwab_account_openapi,
    main,
)


class SchwabAccountSchemaEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.specification = _complete_specification()

    def inspect(self, payload: object | None = None):
        raw = json.dumps(
            self.specification if payload is None else payload,
            sort_keys=True,
        ).encode("utf-8")
        return inspect_schwab_account_openapi(raw)

    def test_complete_schema_is_reviewable_but_never_funding_authority(self) -> None:
        evidence = self.inspect()
        payload = evidence.to_dict()

        self.assertTrue(evidence.ready_for_semantic_review)
        self.assertEqual((), evidence.findings)
        self.assertEqual("/accounts/{accountNumber}", evidence.account_path)
        self.assertEqual("accountNumber", evidence.account_parameter)
        self.assertEqual("getAccount", evidence.account_operation_id)
        self.assertEqual(
            "EXPLICIT_FIELD_REQUIRES_MANUAL_REVIEW",
            evidence.settled_cash_mapping,
        )
        self.assertEqual(
            "CANDIDATE_FIELDS_REQUIRE_MANUAL_REVIEW",
            evidence.restriction_mapping,
        )
        self.assertEqual(
            SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION,
            payload["schemaVersion"],
        )
        self.assertFalse(payload["rawSourceHashRetained"])
        self.assertFalse(payload["fundingGateReady"])
        self.assertFalse(payload["automaticSemanticAcceptance"])
        self.assertTrue(payload["manualSemanticReviewRequired"])
        self.assertTrue(payload["inspectionOnly"])
        self.assertFalse(payload["networkAccessed"])
        self.assertFalse(payload["credentialsAccessed"])
        self.assertFalse(payload["providerEvidence"])
        self.assertFalse(payload["executionPermit"])
        self.assertFalse(payload["brokerActionAllowed"])
        self.assertFalse(payload["retryAllowed"])
        self.assertFalse(payload["transmitting"])
        self.assertEqual("UNAVAILABLE", payload["orderTransmission"])

    def test_live_shape_without_explicit_settled_cash_remains_unavailable(self) -> None:
        live_shape = deepcopy(self.specification)
        current = live_shape["components"]["schemas"]["CurrentBalances"][
            "properties"
        ]
        del current["settledCash"]

        evidence = self.inspect(live_shape)

        self.assertTrue(evidence.ready_for_semantic_review)
        self.assertEqual("UNAVAILABLE", evidence.settled_cash_mapping)
        self.assertIn(
            "No explicit settled-cash field is declared at the reviewed path.",
            evidence.mapping_limitations,
        )
        payload = evidence.to_dict()
        self.assertFalse(payload["fundingGateReady"])
        self.assertFalse(payload["automaticSemanticAcceptance"])

    def test_local_refs_all_of_types_and_description_hashes_are_resolved(self) -> None:
        evidence = self.inspect()

        self.assertIn(
            "securitiesAccount.currentBalances.settledCash",
            evidence.response_field_paths,
        )
        by_name = {
            item.logical_field: item for item in evidence.field_evidence
        }
        self.assertEqual("DIRECT", by_name["settledCash"].availability)
        self.assertEqual("number", by_name["settledCash"].declared_type)
        self.assertTrue(by_name["settledCash"].description_present)
        self.assertEqual(64, len(by_name["settledCash"].description_sha256))
        self.assertEqual(
            "boolean",
            by_name["closingOnlyRestricted"].declared_type,
        )

    def test_description_text_and_values_are_never_retained(self) -> None:
        secret_description = "SYNTHETIC-DESCRIPTION-MUST-NOT-LEAK"
        specification = deepcopy(self.specification)
        specification["components"]["schemas"]["CurrentBalances"]["properties"][
            "settledCash"
        ]["description"] = secret_description

        rendered = json.dumps(
            self.inspect(specification).to_dict(),
            sort_keys=True,
        )

        self.assertNotIn(secret_description, rendered)
        self.assertIn('"descriptionPresent": true', rendered)
        self.assertIn('"descriptionRetained": false', rendered)

    def test_missing_descriptions_keep_mapping_incomplete(self) -> None:
        specification = deepcopy(self.specification)
        del specification["components"]["schemas"]["CurrentBalances"][
            "properties"
        ]["settledCash"]["description"]
        del specification["components"]["schemas"]["SecuritiesAccount"][
            "allOf"
        ][1][
            "properties"
        ]["isClosingOnlyRestricted"]["description"]

        evidence = self.inspect(specification)

        self.assertEqual(
            "EXPLICIT_FIELD_DESCRIPTION_UNAVAILABLE",
            evidence.settled_cash_mapping,
        )
        self.assertEqual(
            "CANDIDATE_FIELDS_DESCRIPTION_UNAVAILABLE",
            evidence.restriction_mapping,
        )
        self.assertFalse(evidence.to_dict()["fundingGateReady"])

    def test_missing_account_get_post_only_and_ambiguous_get_fail_review(self) -> None:
        missing = deepcopy(self.specification)
        missing["paths"] = {}
        missing_evidence = self.inspect(missing)
        self.assertIn(
            "One unambiguous GET account-detail operation was not found.",
            missing_evidence.findings,
        )
        self.assertFalse(missing_evidence.ready_for_semantic_review)

        post_only = deepcopy(self.specification)
        path_item = post_only["paths"]["/accounts/{accountNumber}"]
        path_item["post"] = path_item.pop("get")
        post_evidence = self.inspect(post_only)
        self.assertIn(
            "One unambiguous GET account-detail operation was not found.",
            post_evidence.findings,
        )

        ambiguous = deepcopy(self.specification)
        ambiguous["paths"]["/accounts/{accountHash}"] = deepcopy(
            ambiguous["paths"]["/accounts/{accountNumber}"]
        )
        ambiguous_evidence = self.inspect(ambiguous)
        self.assertIn(
            "One unambiguous GET account-detail operation was not found.",
            ambiguous_evidence.findings,
        )

    def test_account_collection_and_order_paths_do_not_count(self) -> None:
        specification = deepcopy(self.specification)
        operation = specification["paths"].pop(
            "/accounts/{accountNumber}"
        )
        specification["paths"]["/accounts"] = operation
        specification["paths"]["/accounts/{accountNumber}/orders"] = operation

        evidence = self.inspect(specification)

        self.assertIsNone(evidence.account_path)
        self.assertFalse(evidence.ready_for_semantic_review)

    def test_unresolved_response_schema_blocks_review(self) -> None:
        specification = deepcopy(self.specification)
        del specification["paths"]["/accounts/{accountNumber}"]["get"][
            "responses"
        ]["200"]["content"]

        evidence = self.inspect(specification)

        self.assertIn(
            "The GET account-detail response schema could not be resolved.",
            evidence.findings,
        )
        self.assertFalse(evidence.ready_for_semantic_review)

    def test_wrong_server_and_embedded_credentials_are_sanitized(self) -> None:
        specification = deepcopy(self.specification)
        specification["servers"] = [
            {
                "url": (
                    "https://user:password@api.schwabapi.com/trader/v1"
                    "?token=SYNTHETIC#fragment"
                )
            }
        ]

        evidence = self.inspect(specification)
        rendered = json.dumps(evidence.to_dict(), sort_keys=True)

        self.assertIn(
            "The specification does not declare Schwab's exact HTTPS API host.",
            evidence.findings,
        )
        for forbidden in ("user", "password", "SYNTHETIC"):
            self.assertNotIn(forbidden, rendered)

    def test_portal_envelope_hashes_only_nested_specification(self) -> None:
        first = {
            "appKey": "SYNTHETIC-APP-KEY-ONE",
            "appSecret": "SYNTHETIC-SECRET-ONE",
            "specification": json.dumps(self.specification),
        }
        second = {
            "appKey": "SYNTHETIC-APP-KEY-TWO",
            "appSecret": "SYNTHETIC-SECRET-TWO",
            "specification": json.dumps(self.specification),
        }

        first_evidence = self.inspect(first)
        second_evidence = self.inspect(second)
        rendered = json.dumps(first_evidence.to_dict(), sort_keys=True)

        self.assertEqual(
            first_evidence.specification_sha256,
            second_evidence.specification_sha256,
        )
        self.assertEqual(
            ("appKey", "appSecret"),
            first_evidence.sensitive_envelope_fields,
        )
        self.assertFalse(first_evidence.ready_for_semantic_review)
        self.assertFalse(first_evidence.to_dict()["rawSourceHashRetained"])
        for forbidden in (
            "SYNTHETIC-APP-KEY-ONE",
            "SYNTHETIC-SECRET-ONE",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_invalid_json_shape_and_size_are_rejected(self) -> None:
        for payload, message in (
            (b"", "non-empty bytes"),
            (b"{", "valid UTF-8 JSON"),
            (b"[]", "JSON object"),
            (b'{"id":"missing"}', "does not contain an OpenAPI specification"),
        ):
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    SchwabAccountSchemaEvidenceError,
                    message,
                ):
                    inspect_schwab_account_openapi(payload)
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "size limit",
        ):
            inspect_schwab_account_openapi(
                b"{" + b" " * MAX_OPENAPI_EXPORT_BYTES
            )
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "unsupported JSON values",
        ):
            inspect_schwab_account_openapi(
                b'{"openapi":"3.0.3","notFinite":NaN}'
            )

    def test_external_broken_and_cyclic_refs_fail_without_network(self) -> None:
        external = deepcopy(self.specification)
        external["paths"]["/accounts/{accountNumber}"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["$ref"] = (
            "https://example.invalid/account.json"
        )
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "Only local OpenAPI references",
        ):
            self.inspect(external)

        broken = deepcopy(self.specification)
        broken["paths"]["/accounts/{accountNumber}"]["get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["$ref"] = (
            "#/components/schemas/Missing"
        )
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "could not be resolved",
        ):
            self.inspect(broken)

        cyclic = deepcopy(self.specification)
        cyclic["components"]["schemas"]["Account"]["$ref"] = (
            "#/components/schemas/Account"
        )
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "reference cycle",
        ):
            self.inspect(cyclic)

        recursive_property = deepcopy(self.specification)
        recursive_property["components"]["schemas"]["SecuritiesAccount"][
            "allOf"
        ][0]["properties"]["recursive"] = {
            "$ref": "#/components/schemas/SecuritiesAccount"
        }
        with self.assertRaisesRegex(
            SchwabAccountSchemaEvidenceError,
            "reference cycle",
        ):
            self.inspect(recursive_property)

    def test_input_mapping_is_not_mutated(self) -> None:
        original = deepcopy(self.specification)

        self.inspect(self.specification)

        self.assertEqual(original, self.specification)

    def test_cli_reads_regular_local_file_and_prints_sanitized_evidence(self) -> None:
        envelope = {
            "appKey": "SYNTHETIC-APP-KEY",
            "appSecret": "SYNTHETIC-SECRET",
            "specification": json.dumps(self.specification),
        }
        with TemporaryDirectory() as directory:
            export_path = Path(directory) / "official-export.json"
            export_path.write_text(json.dumps(envelope), encoding="utf-8")
            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                exit_code = main([str(export_path)])

        self.assertEqual(0, exit_code)
        self.assertEqual("", errors.getvalue())
        payload = json.loads(output.getvalue())
        self.assertEqual(
            SCHWAB_ACCOUNT_SCHEMA_EVIDENCE_VERSION,
            payload["schemaVersion"],
        )
        self.assertNotIn("SYNTHETIC-APP-KEY", output.getvalue())
        self.assertNotIn("SYNTHETIC-SECRET", output.getvalue())
        self.assertFalse(payload["rawSourceHashRetained"])
        self.assertFalse(payload["networkAccessed"])
        self.assertFalse(payload["brokerActionAllowed"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_cli_rejects_symlink_and_missing_path_without_echoing_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.json"
            source.write_text(json.dumps(self.specification), encoding="utf-8")
            link = root / "secret-looking-export.json"
            try:
                link.symlink_to(source)
            except OSError:
                self.skipTest("symlink creation not permitted")
            output = StringIO()
            errors = StringIO()
            with redirect_stdout(output), redirect_stderr(errors):
                link_exit = main([str(link)])
                missing_exit = main([str(root / "missing-secret.json")])

        self.assertEqual(2, link_exit)
        self.assertEqual(2, missing_exit)
        self.assertEqual("", output.getvalue())
        self.assertNotIn("secret-looking-export", errors.getvalue())
        self.assertNotIn("missing-secret", errors.getvalue())
        for line in errors.getvalue().splitlines():
            payload = json.loads(line)
            self.assertEqual("BLOCKED", payload["status"])
            self.assertFalse(payload["networkAccessed"])
            self.assertFalse(payload["transmitting"])

    def test_invalid_cli_argument_is_generic(self) -> None:
        errors = StringIO()
        with redirect_stderr(errors), self.assertRaises(SystemExit):
            main(["--secret-looking-value"])

        self.assertIn("invalid arguments", errors.getvalue())
        self.assertNotIn("--secret-looking-value", errors.getvalue())

    def test_module_has_no_network_credential_file_write_or_order_surface(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "momentum_hunter"
            / "schwab_account_schema_evidence.py"
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
            "submit_order",
            "place_order",
            "replace_order",
            "cancel_order",
            "/orders",
        ):
            self.assertNotIn(forbidden, source)


def _complete_specification() -> dict[str, object]:
    account_response = {
        "description": "Account detail",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/Account"}
            }
        },
    }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "Synthetic Schwab Trader API account fixture",
            "version": "1.0.0",
        },
        "servers": [{"url": "https://api.schwabapi.com/trader/v1"}],
        "paths": {
            "/accounts/{accountNumber}": {
                "get": {
                    "operationId": "getAccount",
                    "responses": {"200": account_response},
                }
            }
        },
        "components": {
            "schemas": {
                "Account": {
                    "type": "object",
                    "properties": {
                        "securitiesAccount": {
                            "$ref": "#/components/schemas/SecuritiesAccount"
                        },
                        "aggregatedBalance": {
                            "type": "object",
                            "properties": {
                                "currentLiquidationValue": {
                                    "type": "number",
                                    "description": "Synthetic aggregate value.",
                                }
                            },
                        },
                    },
                },
                "SecuritiesAccount": {
                    "allOf": [
                        {
                            "type": "object",
                            "properties": {
                                "currentBalances": {
                                    "$ref": "#/components/schemas/CurrentBalances"
                                },
                                "initialBalances": {
                                    "$ref": "#/components/schemas/InitialBalances"
                                },
                            },
                        },
                        {
                            "type": "object",
                            "properties": {
                                "isClosingOnlyRestricted": {
                                    "type": "boolean",
                                    "description": (
                                        "Synthetic closing-only indicator."
                                    ),
                                },
                                "pfcbFlag": {
                                    "type": "boolean",
                                    "description": "Synthetic account flag.",
                                },
                            },
                        },
                    ]
                },
                "CurrentBalances": {
                    "type": "object",
                    "properties": {
                        "settledCash": {
                            "type": "number",
                            "description": "Synthetic settled cash field.",
                        },
                        "unsettledCash": {
                            "type": "number",
                            "description": "Synthetic unsettled cash field.",
                        },
                        "cashAvailableForTrading": {
                            "type": "number",
                            "description": "Synthetic available cash field.",
                        },
                        "cashAvailableForWithdrawal": {
                            "type": "number",
                            "description": "Synthetic withdrawal field.",
                        },
                    },
                },
                "InitialBalances": {
                    "type": "object",
                    "properties": {
                        "isInCall": {
                            "type": "boolean",
                            "description": "Synthetic call indicator.",
                        }
                    },
                },
            }
        },
    }


if __name__ == "__main__":
    unittest.main()
