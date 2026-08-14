from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

from momentum_hunter.research_data_basis import (
    ACQUIRED,
    ACTION_VERIFIED,
    ACTIVE,
    AMBIGUOUS,
    BASIS_ASSERTED,
    BASIS_UNKNOWN,
    BASIS_VERIFIED,
    CORPORATE_ACTION_FEATURE_FAMILY,
    CORPORATE_ACTION_UNRESOLVED,
    CURRENT_ONLY,
    DATA_BASIS_UNCERTAIN,
    DELISTED,
    EVIDENCE_DERIVED,
    EXECUTION_AUTHORITY,
    FORWARD_SPLIT,
    IDENTITY_PARTIAL,
    IDENTITY_UNRESOLVED,
    IDENTITY_VERIFIED,
    MERGER,
    OhlcvSnapshot,
    POINT_IN_TIME,
    RAW_PROVIDER,
    RENAMED,
    RESOLVED,
    REVERSE_SPLIT,
    SAFE_FOR_RAW_ANALYSIS,
    SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS,
    SECURITY_IDENTITY_UNRESOLVED,
    SPECIALIST_ABSTENTION_CODE,
    SPLIT_ADJUSTED,
    SURVIVORSHIP_CONTROLLED,
    SURVIVORSHIP_PARTIAL,
    SURVIVORSHIP_STATUS_UNCONTROLLED,
    SURVIVORSHIP_UNCONTROLLED,
    SYMBOL_CHANGE,
    UNKNOWN_PRICE_BASIS,
    UNRESOLVED,
    ResearchDataBasisError,
    assess_research_price_basis,
    assess_survivorship_bias,
    build_corporate_action,
    build_dataset_compatibility_report,
    build_research_price_bar,
    build_security_identity,
    build_symbol_alias,
    compare_technical_basis,
    load_security_identity_json,
    research_price_bar_fingerprint,
    resolve_security_identity,
    transformation_lineage_fingerprint,
    transform_split_adjusted_bar,
    validate_corporate_action,
    validate_research_price_bar,
    validate_transformation_lineage,
    write_dataset_compatibility_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
DATA_001_REPORT = (
    ROOT
    / "docs"
    / "argus-office"
    / "reports"
    / "architecture"
    / "ARGUS-RESEARCH-DATA-001-research-data-inventory.json"
)
FP_A = "A" * 64
FP_B = "B" * 64
FP_C = "C" * 64


class SecurityIdentityTests(unittest.TestCase):
    def test_ticker_change_resolves_by_historical_effective_date(self) -> None:
        identity = _renamed_identity()

        old = resolve_security_identity(
            (identity,), symbol="ABC", observed_on="2025-05-02"
        )
        new = resolve_security_identity(
            (identity,), symbol="DEF", observed_on="2025-05-03"
        )

        self.assertEqual(RESOLVED, old.status)
        self.assertEqual("SEC-001", old.security_id)
        self.assertEqual("ABC", old.alias.symbol if old.alias else None)
        self.assertEqual(RESOLVED, new.status)
        self.assertEqual("DEF", new.alias.symbol if new.alias else None)
        self.assertEqual("DEF", identity.current_symbol)
        self.assertEqual(RENAMED, identity.security_state)

    def test_same_symbol_reused_by_different_security_uses_time_not_ticker(self) -> None:
        old_identity = _identity(
            security_id="SEC-OLD",
            symbol="XYZ",
            start="2010-01-01",
            end="2018-12-31",
            state=DELISTED,
        )
        new_identity = _identity(
            security_id="SEC-NEW",
            symbol="XYZ",
            start="2021-01-01",
            end=None,
            state=ACTIVE,
        )

        old = resolve_security_identity(
            (old_identity, new_identity), symbol="XYZ", observed_on="2015-06-01"
        )
        new = resolve_security_identity(
            (old_identity, new_identity), symbol="XYZ", observed_on="2024-06-01"
        )

        self.assertEqual("SEC-OLD", old.security_id)
        self.assertEqual("SEC-NEW", new.security_id)

    def test_overlapping_cross_security_symbol_claim_is_ambiguous(self) -> None:
        first = _identity(
            security_id="SEC-A", symbol="XYZ", start="2020-01-01", end=None
        )
        second = _identity(
            security_id="SEC-B", symbol="XYZ", start="2021-01-01", end=None
        )

        result = resolve_security_identity(
            (first, second), symbol="XYZ", observed_on="2024-01-01"
        )

        self.assertEqual(AMBIGUOUS, result.status)
        self.assertIn("SYMBOL_REUSED_OR_ALIAS_OVERLAP", result.findings)

    def test_missing_effective_date_and_overlapping_aliases_fail_closed(self) -> None:
        with self.assertRaises(ResearchDataBasisError):
            build_symbol_alias(
                symbol="ABC",
                effective_from="",
                effective_to=None,
                exchange=None,
                source="fixture",
                evidence_fingerprint=FP_A,
            )
        first = _alias("ABC", "2020-01-01", "2025-05-03", FP_A)
        second = _alias("DEF", "2025-05-03", None, FP_B)
        with self.assertRaisesRegex(ResearchDataBasisError, "overlapped"):
            build_security_identity(
                security_id="SEC-001",
                current_symbol="DEF",
                aliases=(first, second),
                security_state=ACTIVE,
                issuer_id=None,
                issuer_name=None,
                identity_sources=("fixture",),
                identity_status=IDENTITY_VERIFIED,
            )

    def test_delisted_security_remains_historically_resolvable(self) -> None:
        identity = _identity(
            security_id="SEC-DEAD",
            symbol="OLD",
            start="2011-01-01",
            end="2020-02-03",
            state=DELISTED,
        )

        historical = resolve_security_identity(
            (identity,), symbol="OLD", observed_on="2019-06-01"
        )
        current = resolve_security_identity(
            (identity,), symbol="OLD", observed_on="2024-06-01"
        )

        self.assertEqual(RESOLVED, historical.status)
        self.assertEqual(UNRESOLVED, current.status)
        self.assertEqual(DELISTED, identity.security_state)

    def test_serialized_identity_rejects_duplicate_keys_and_tampering(self) -> None:
        identity = _renamed_identity()
        payload = json.dumps(asdict(identity), sort_keys=True)
        loaded = load_security_identity_json(payload)
        self.assertEqual(identity, loaded)

        duplicate = payload[:-1] + ',"security_id":"SEC-EVIL"}'
        with self.assertRaisesRegex(ResearchDataBasisError, "Duplicate JSON key"):
            load_security_identity_json(duplicate)

        tampered = json.loads(payload)
        tampered["current_symbol"] = "ZZZ"
        with self.assertRaises(ResearchDataBasisError):
            load_security_identity_json(json.dumps(tampered))

        missing_fingerprint = json.loads(payload)
        missing_fingerprint.pop("fingerprint")
        with self.assertRaisesRegex(ResearchDataBasisError, "fingerprint"):
            load_security_identity_json(json.dumps(missing_fingerprint))

        wrong_schema = json.loads(payload)
        wrong_schema["schema_version"] = 2
        with self.assertRaisesRegex(ResearchDataBasisError, "schema"):
            load_security_identity_json(json.dumps(wrong_schema))


class CorporateActionTransformationTests(unittest.TestCase):
    def test_required_split_ratios_transform_price_and_volume_consistently(self) -> None:
        cases = (
            (FORWARD_SPLIT, 2, 1, "0.5", "2", "30", "2000"),
            (FORWARD_SPLIT, 3, 2, "0.6666666666666666666666666667", "1.5", "40", "1500"),
            (FORWARD_SPLIT, 10, 1, "0.1", "10", "6", "10000"),
            (REVERSE_SPLIT, 1, 10, "10", "0.1", "600", "100"),
        )
        identity = _identity(
            security_id="SEC-SPLIT", symbol="SPLT", start="2020-01-01", end=None
        )
        raw = _bar(
            bar_id="bar-1",
            security_id="SEC-SPLIT",
            symbol="SPLT",
            timestamp="2024-01-01T16:00:00+00:00",
            close="60",
            volume="1000",
        )
        for kind, numerator, denominator, price_factor, volume_factor, close, volume in cases:
            with self.subTest(kind=kind, ratio=f"{numerator}:{denominator}"):
                action = _split_action(
                    action_id=f"split-{numerator}-{denominator}",
                    security_id="SEC-SPLIT",
                    action_type=kind,
                    numerator=numerator,
                    denominator=denominator,
                )
                lineage = transform_split_adjusted_bar(
                    raw,
                    identity=identity,
                    actions=(action,),
                    target_as_of="2024-01-03T16:00:00+00:00",
                )
                self.assertEqual(price_factor, lineage.cumulative_price_factor)
                self.assertEqual(volume_factor, lineage.cumulative_volume_factor)
                self.assertEqual(close, lineage.transformed_ohlcv.close)
                self.assertEqual(volume, lineage.transformed_ohlcv.volume)
                self.assertEqual(raw.close, lineage.original_ohlcv.close)
                self.assertEqual(raw.fingerprint, lineage.raw_bar_fingerprint)

    def test_symbol_change_has_identity_lineage_and_no_numeric_effect(self) -> None:
        identity = _renamed_identity()
        raw = _bar(
            bar_id="bar-old",
            security_id="SEC-001",
            symbol="ABC",
            timestamp="2025-05-02T16:00:00+00:00",
            close="30",
            volume="500",
        )
        action = build_corporate_action(
            action_id="symbol-change-1",
            security_id="SEC-001",
            action_type=SYMBOL_CHANGE,
            announcement_at=None,
            effective_at="2025-05-03T00:00:00+00:00",
            ratio_numerator=None,
            ratio_denominator=None,
            old_symbol="ABC",
            new_symbol="DEF",
            source="fixture",
            evidence_fingerprint=FP_B,
            verification_status=ACTION_VERIFIED,
        )

        lineage = transform_split_adjusted_bar(
            raw,
            identity=identity,
            actions=(action,),
            target_as_of="2025-05-04T00:00:00+00:00",
        )

        self.assertEqual("1", lineage.cumulative_price_factor)
        self.assertEqual(lineage.original_ohlcv, lineage.transformed_ohlcv)
        self.assertEqual(("symbol-change-1",), lineage.corporate_action_ids)

    def test_symbol_change_must_match_point_in_time_alias_chain(self) -> None:
        identity = _renamed_identity()
        raw = _bar(
            bar_id="bar-old",
            security_id="SEC-001",
            symbol="ABC",
            timestamp="2025-05-02T16:00:00+00:00",
            close="30",
            volume="500",
        )
        wrong = build_corporate_action(
            action_id="symbol-change-wrong",
            security_id="SEC-001",
            action_type=SYMBOL_CHANGE,
            announcement_at=None,
            effective_at="2025-05-03T00:00:00+00:00",
            ratio_numerator=None,
            ratio_denominator=None,
            old_symbol="XYZ",
            new_symbol="DEF",
            source="fixture",
            evidence_fingerprint=FP_C,
            verification_status=ACTION_VERIFIED,
        )

        with self.assertRaisesRegex(ResearchDataBasisError, "alias chain"):
            transform_split_adjusted_bar(
                raw,
                identity=identity,
                actions=(wrong,),
                target_as_of="2025-05-04T00:00:00+00:00",
            )

    def test_recomputed_fingerprint_does_not_bypass_bar_validation(self) -> None:
        raw = _bar(
            bar_id="bar-forged",
            security_id="SEC-001",
            symbol="ABC",
            timestamp="2025-05-02T16:00:00+00:00",
            close="30",
            volume="500",
        )
        forged = replace(raw, high="20", fingerprint="")
        forged = replace(
            forged, fingerprint=research_price_bar_fingerprint(forged)
        )

        with self.assertRaisesRegex(ResearchDataBasisError, "high contradicted"):
            validate_research_price_bar(forged)

    def test_malformed_zero_negative_and_wrong_direction_ratios_fail(self) -> None:
        bad = (
            (FORWARD_SPLIT, 0, 1),
            (FORWARD_SPLIT, -2, 1),
            (FORWARD_SPLIT, 1, 2),
            (REVERSE_SPLIT, 2, 1),
            (REVERSE_SPLIT, 1, 0),
        )
        for kind, numerator, denominator in bad:
            with self.subTest(kind=kind, numerator=numerator, denominator=denominator):
                with self.assertRaises(ResearchDataBasisError):
                    _split_action(
                        action_id="bad-split",
                        security_id="SEC-A",
                        action_type=kind,
                        numerator=numerator,
                        denominator=denominator,
                    )

    def test_wrong_security_duplicate_and_out_of_range_action_fail(self) -> None:
        identity = _identity(
            security_id="SEC-A", symbol="AAA", start="2020-01-01", end=None
        )
        raw = _bar(
            bar_id="bar-a",
            security_id="SEC-A",
            symbol="AAA",
            timestamp="2024-01-01T16:00:00+00:00",
            close="60",
            volume="1000",
        )
        wrong = _split_action(
            action_id="wrong", security_id="SEC-B", action_type=FORWARD_SPLIT
        )
        with self.assertRaisesRegex(ResearchDataBasisError, "another security"):
            transform_split_adjusted_bar(
                raw,
                identity=identity,
                actions=(wrong,),
                target_as_of="2024-01-03T16:00:00+00:00",
            )
        valid = _split_action(
            action_id="valid", security_id="SEC-A", action_type=FORWARD_SPLIT
        )
        with self.assertRaisesRegex(ResearchDataBasisError, "applied twice"):
            transform_split_adjusted_bar(
                raw,
                identity=identity,
                actions=(valid, valid),
                target_as_of="2024-01-03T16:00:00+00:00",
            )
        with self.assertRaisesRegex(ResearchDataBasisError, "outside the valid range"):
            transform_split_adjusted_bar(
                raw,
                identity=identity,
                actions=(valid,),
                target_as_of="2024-01-01T20:00:00+00:00",
            )

    def test_tampered_action_and_lineage_fail_closed(self) -> None:
        identity = _identity(
            security_id="SEC-A", symbol="AAA", start="2020-01-01", end=None
        )
        raw = _bar(
            bar_id="bar-a",
            security_id="SEC-A",
            symbol="AAA",
            timestamp="2024-01-01T16:00:00+00:00",
            close="60",
            volume="1000",
        )
        action = _split_action(
            action_id="split-a", security_id="SEC-A", action_type=FORWARD_SPLIT
        )
        tampered_action = replace(action, ratio_numerator=10)
        with self.assertRaisesRegex(ResearchDataBasisError, "fingerprint"):
            validate_corporate_action(tampered_action)

        lineage = transform_split_adjusted_bar(
            raw,
            identity=identity,
            actions=(action,),
            target_as_of="2024-01-03T16:00:00+00:00",
        )
        forged = replace(
            lineage,
            transformed_ohlcv=replace(lineage.transformed_ohlcv, close="999"),
            fingerprint="",
        )
        forged = replace(forged, fingerprint=transformation_lineage_fingerprint(forged))
        with self.assertRaisesRegex(ResearchDataBasisError, "did not reconcile"):
            validate_transformation_lineage(
                forged,
                raw_bar=raw,
                identity=identity,
                actions=(action,),
                target_as_of="2024-01-03T16:00:00+00:00",
            )

    def test_unsupported_action_semantics_remain_extension_only(self) -> None:
        identity = _identity(
            security_id="SEC-A", symbol="AAA", start="2020-01-01", end=None
        )
        raw = _bar(
            bar_id="bar-a",
            security_id="SEC-A",
            symbol="AAA",
            timestamp="2024-01-01T16:00:00+00:00",
            close="60",
            volume="1000",
        )
        merger = build_corporate_action(
            action_id="merger-a",
            security_id="SEC-A",
            action_type=MERGER,
            announcement_at=None,
            effective_at="2024-01-02T00:00:00+00:00",
            ratio_numerator=None,
            ratio_denominator=None,
            old_symbol=None,
            new_symbol=None,
            source="fixture",
            evidence_fingerprint=FP_A,
            verification_status=ACTION_VERIFIED,
        )
        with self.assertRaisesRegex(ResearchDataBasisError, "no transformation semantics"):
            transform_split_adjusted_bar(
                raw,
                identity=identity,
                actions=(merger,),
                target_as_of="2024-01-03T00:00:00+00:00",
            )


class AdmissionAndBiasTests(unittest.TestCase):
    def test_basis_admission_is_research_only_and_specialist_compatible(self) -> None:
        safe = assess_research_price_basis(
            requested_basis=RAW_PROVIDER,
            observed_basis=RAW_PROVIDER,
            basis_verification=BASIS_VERIFIED,
            identity_status=IDENTITY_VERIFIED,
            corporate_action_status=RESOLVED,
            applicable_action_count=0,
            transformation_lineage_valid=False,
            survivorship_status=SURVIVORSHIP_CONTROLLED,
            require_survivorship_control=True,
        )

        self.assertEqual(SAFE_FOR_RAW_ANALYSIS, safe.status)
        self.assertEqual(EXECUTION_AUTHORITY, safe.execution_authority)
        self.assertEqual(CORPORATE_ACTION_FEATURE_FAMILY, safe.specialist_feature_family)
        self.assertEqual(DATA_BASIS_UNCERTAIN, safe.specialist_abstention_code)

    def test_split_adjusted_requires_verified_lineage_or_no_applicable_action(self) -> None:
        safe = assess_research_price_basis(
            requested_basis=SPLIT_ADJUSTED,
            observed_basis=SPLIT_ADJUSTED,
            basis_verification=BASIS_VERIFIED,
            identity_status=IDENTITY_VERIFIED,
            corporate_action_status=RESOLVED,
            applicable_action_count=1,
            transformation_lineage_valid=True,
            survivorship_status=SURVIVORSHIP_CONTROLLED,
            require_survivorship_control=True,
        )
        uncertain = assess_research_price_basis(
            requested_basis=SPLIT_ADJUSTED,
            observed_basis=SPLIT_ADJUSTED,
            basis_verification=BASIS_ASSERTED,
            identity_status=IDENTITY_VERIFIED,
            corporate_action_status=RESOLVED,
            applicable_action_count=1,
            transformation_lineage_valid=True,
            survivorship_status=SURVIVORSHIP_CONTROLLED,
            require_survivorship_control=True,
        )

        self.assertEqual(SAFE_FOR_SPLIT_ADJUSTED_ANALYSIS, safe.status)
        self.assertEqual(DATA_BASIS_UNCERTAIN, uncertain.status)

    def test_unknown_identity_basis_action_and_survivorship_each_fail_closed(self) -> None:
        base = {
            "requested_basis": SPLIT_ADJUSTED,
            "observed_basis": SPLIT_ADJUSTED,
            "basis_verification": BASIS_VERIFIED,
            "identity_status": IDENTITY_VERIFIED,
            "corporate_action_status": RESOLVED,
            "applicable_action_count": 1,
            "transformation_lineage_valid": True,
            "survivorship_status": SURVIVORSHIP_CONTROLLED,
            "require_survivorship_control": True,
        }
        cases = (
            ("identity_status", IDENTITY_UNRESOLVED, SECURITY_IDENTITY_UNRESOLVED),
            ("observed_basis", UNKNOWN_PRICE_BASIS, DATA_BASIS_UNCERTAIN),
            ("corporate_action_status", UNRESOLVED, CORPORATE_ACTION_UNRESOLVED),
            (
                "survivorship_status",
                SURVIVORSHIP_UNCONTROLLED,
                SURVIVORSHIP_STATUS_UNCONTROLLED,
            ),
        )
        for field_name, value, expected in cases:
            with self.subTest(field_name=field_name):
                values = dict(base)
                values[field_name] = value
                result = assess_research_price_basis(**values)
                self.assertEqual(expected, result.status)
                self.assertEqual((), result.allowed_uses)

    def test_current_only_universe_cannot_claim_survivorship_controlled(self) -> None:
        result = assess_survivorship_bias(
            membership_basis=CURRENT_ONLY,
            inactive_security_coverage="NONE",
            declared_status=SURVIVORSHIP_CONTROLLED,
        )
        partial = assess_survivorship_bias(
            membership_basis=POINT_IN_TIME,
            inactive_security_coverage="PARTIAL",
        )

        self.assertEqual(SURVIVORSHIP_UNCONTROLLED, result.status)
        self.assertIn("FALSE_SURVIVORSHIP_ASSERTION", result.findings)
        self.assertEqual(SURVIVORSHIP_PARTIAL, partial.status)


class TechnicalBasisSafetyTests(unittest.TestCase):
    def test_unnormalized_split_corrupts_every_required_research_shape(self) -> None:
        raw_closes = ("100", "105", "110", "10.5", "10")
        adjusted_closes = ("10", "10.5", "11", "10.5", "10")
        raw = tuple(
            _series_bar(index, close, basis=RAW_PROVIDER)
            for index, close in enumerate(raw_closes)
        )
        adjusted = tuple(
            _series_bar(index, close, basis=SPLIT_ADJUSTED)
            for index, close in enumerate(adjusted_closes)
        )

        comparison = compare_technical_basis(raw, adjusted)

        self.assertTrue(all(comparison["contaminated"].values()))
        self.assertLess(comparison["raw"]["periodReturn"], -0.8)
        self.assertEqual(0.0, comparison["adjusted"]["periodReturn"])

    def test_basis_comparison_rejects_misaligned_observations(self) -> None:
        raw = tuple(
            _series_bar(index, "10", basis=RAW_PROVIDER) for index in range(5)
        )
        adjusted = list(
            _series_bar(index, "10", basis=SPLIT_ADJUSTED) for index in range(5)
        )
        adjusted[2] = _series_bar(6, "10", basis=SPLIT_ADJUSTED)

        with self.assertRaisesRegex(ResearchDataBasisError, "aligned identities"):
            compare_technical_basis(raw, adjusted)


class DatasetCompatibilityTests(unittest.TestCase):
    def test_current_inventory_stays_unknown_uncontrolled_and_provider_minimal(self) -> None:
        inventory = json.loads(DATA_001_REPORT.read_text(encoding="utf-8"))

        report = build_dataset_compatibility_report(
            inventory, as_of="2026-08-14T16:00:00-05:00"
        )

        self.assertEqual(5, len(report["datasets"]))
        self.assertEqual("NOT_PERFORMED", report["providerSelection"])
        self.assertEqual("INSUFFICIENT", report["pointInTimeUniverseCapability"])
        self.assertEqual(SURVIVORSHIP_UNCONTROLLED, report["survivorshipBiasStatus"])
        for dataset in report["datasets"]:
            self.assertFalse(dataset["stableSecurityIdentity"])
            self.assertFalse(dataset["historicalAliases"])
            self.assertFalse(dataset["delistedSecurityCoverage"])
            self.assertFalse(dataset["pointInTimeMembership"])
            self.assertEqual(UNKNOWN_PRICE_BASIS, dataset["priceBasis"])
            self.assertIn("SURVIVORSHIP_SAFE_STATISTICS", dataset["unsafeFor"])
        self.assertEqual(4, len(report["gaps"]))

    def test_compatibility_report_is_deterministic_write_once_and_nonmutating(self) -> None:
        before = DATA_001_REPORT.read_bytes()
        inventory = json.loads(before)
        first = build_dataset_compatibility_report(
            inventory, as_of="2026-08-14T16:00:00-05:00"
        )
        second = build_dataset_compatibility_report(
            inventory, as_of="2026-08-14T16:00:00-05:00"
        )
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            json_path = root / "compatibility.json"
            md_path = root / "compatibility.md"
            write_dataset_compatibility_outputs(
                first, json_path=json_path, markdown_path=md_path
            )
            exact_json = json_path.read_bytes()
            exact_md = md_path.read_bytes()
            write_dataset_compatibility_outputs(
                first, json_path=json_path, markdown_path=md_path
            )
            self.assertEqual(exact_json, json_path.read_bytes())
            self.assertEqual(exact_md, md_path.read_bytes())
            conflict = dict(first)
            conflict["classification"] = "CONFLICT"
            with self.assertRaises(ResearchDataBasisError):
                write_dataset_compatibility_outputs(
                    conflict, json_path=json_path, markdown_path=md_path
                )
        self.assertEqual(before, DATA_001_REPORT.read_bytes())

    def test_tampered_data_001_inventory_is_rejected(self) -> None:
        inventory = json.loads(DATA_001_REPORT.read_text(encoding="utf-8"))
        inventory["providerSelection"] = "SOMETHING_ELSE"

        with self.assertRaisesRegex(ResearchDataBasisError, "fingerprint"):
            build_dataset_compatibility_report(
                inventory, as_of="2026-08-14T16:00:00-05:00"
            )

    def test_module_has_no_network_broker_or_runtime_imports(self) -> None:
        source = (ROOT / "momentum_hunter" / "research_data_basis.py").read_text(
            encoding="utf-8"
        )
        prohibited = (
            "import requests",
            "import httpx",
            "import socket",
            "import websocket",
            "submit_order",
            "cancel_order",
            "replace_order",
            "RiskGovernor",
            "TradePlan",
            "AutomationService",
        )
        for token in prohibited:
            self.assertNotIn(token, source)


def _alias(symbol: str, start: str, end: str | None, fingerprint: str):
    return build_symbol_alias(
        symbol=symbol,
        effective_from=start,
        effective_to=end,
        exchange="NASDAQ",
        source="fixture",
        evidence_fingerprint=fingerprint,
    )


def _identity(
    *,
    security_id: str,
    symbol: str,
    start: str,
    end: str | None,
    state: str = ACTIVE,
):
    return build_security_identity(
        security_id=security_id,
        current_symbol=symbol,
        aliases=(_alias(symbol, start, end, FP_A),),
        security_state=state,
        issuer_id=f"ISSUER-{security_id}",
        issuer_name=f"Issuer {security_id}",
        identity_sources=("fixture",),
        identity_status=IDENTITY_VERIFIED,
    )


def _renamed_identity():
    return build_security_identity(
        security_id="SEC-001",
        current_symbol="DEF",
        aliases=(
            _alias("ABC", "2024-01-01", "2025-05-02", FP_A),
            _alias("DEF", "2025-05-03", None, FP_B),
        ),
        security_state=RENAMED,
        issuer_id="ISSUER-001",
        issuer_name="Example Issuer",
        identity_sources=("fixture",),
        identity_status=IDENTITY_VERIFIED,
    )


def _split_action(
    *,
    action_id: str,
    security_id: str,
    action_type: str,
    numerator: int = 2,
    denominator: int = 1,
):
    return build_corporate_action(
        action_id=action_id,
        security_id=security_id,
        action_type=action_type,
        announcement_at="2023-12-15T14:00:00+00:00",
        effective_at="2024-01-02T00:00:00+00:00",
        ratio_numerator=numerator,
        ratio_denominator=denominator,
        old_symbol=None,
        new_symbol=None,
        source="fixture",
        evidence_fingerprint=FP_C,
        verification_status=ACTION_VERIFIED,
    )


def _bar(
    *,
    bar_id: str,
    security_id: str,
    symbol: str,
    timestamp: str,
    close: str,
    volume: str,
    basis: str = RAW_PROVIDER,
):
    close_value = float(close)
    return build_research_price_bar(
        bar_id=bar_id,
        security_id=security_id,
        symbol=symbol,
        timestamp=timestamp,
        open_value=str(close_value),
        high=str(close_value * 1.01),
        low=str(close_value * 0.99),
        close=close,
        volume=volume,
        source="fixture",
        price_basis=basis,
        basis_verification=BASIS_VERIFIED,
        evidence_fingerprint=FP_A,
    )


def _series_bar(index: int, close: str, *, basis: str):
    return _bar(
        bar_id=f"series-{basis}-{index}",
        security_id="SEC-SERIES",
        symbol="SER",
        timestamp=f"2024-01-0{index + 1}T16:00:00+00:00",
        close=close,
        volume="1000",
        basis=basis,
    )


if __name__ == "__main__":
    unittest.main()
