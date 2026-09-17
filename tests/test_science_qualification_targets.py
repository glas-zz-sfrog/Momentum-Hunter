from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from momentum_hunter import continuous_host_contract as contract
from tests.test_continuous_host_boundaries import configuration, seal


class QualificationTargetAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-015-Config-")
        self.addCleanup(self.temp.cleanup)
        self.config = configuration(Path(self.temp.name))
        self.config["qualificationServiceTargets"] = {
            "manifest": "qualification-targets.json", "sha256": "a" * 64,
        }
        for name in ("providerAuthority", "paperAuthority", "liveAuthority"):
            self.config[name] = "NONE"
        seal(self.config)

    def test_offline_reference_retains_complete_host_validation(self):
        self.assertEqual(contract.validate_host(self.config)["inputMode"], contract.OFFLINE)
        self.config["runtimeStateRoot"] = self.config["evidenceRoot"]
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError):
            contract.validate_host(self.config)

    def test_legacy_and_live_reject_even_empty_override_before_early_return(self):
        for version in (1, 2):
            for value in (None, {}, self.config["qualificationServiceTargets"]):
                config = deepcopy(self.config)
                config["schemaVersion"] = version
                config["inputMode"] = contract.LIVE
                config["qualificationServiceTargets"] = value
                seal(config)
                with self.subTest(version=version, value=value), self.assertRaises(contract.HostConfigurationError):
                    contract.input_mode(config)

    def test_missing_mode_and_alias_are_not_defaults(self):
        for name in ("inputMode", "schemaVersion"):
            config = deepcopy(self.config)
            config.pop(name)
            with self.subTest(name=name), self.assertRaises(contract.HostConfigurationError):
                contract.input_mode(config)
        self.config["QualificationServiceTargets"] = self.config["qualificationServiceTargets"]
        with self.assertRaises(contract.HostConfigurationError):
            contract.input_mode(self.config)

    def test_override_requires_integer_schema_not_json_numeric_coercion(self):
        for value in (2.0, "2", True, None):
            config = deepcopy(self.config)
            config["schemaVersion"] = value
            with self.subTest(value=value), self.assertRaises(contract.HostConfigurationError):
                contract.input_mode(config)

    def test_reference_and_authority_negative_matrix(self):
        mutations = [
            lambda c: c["qualificationServiceTargets"].update(manifest="../targets.json"),
            lambda c: c["qualificationServiceTargets"].update(sha256="A" * 64),
            lambda c: c["qualificationServiceTargets"].update(unknown=True),
            lambda c: c.update(qualificationServiceTargets=[]),
        ]
        for name in ("providerAuthority", "paperAuthority", "liveAuthority"):
            mutations.append(lambda c, key=name: c.update({key: "AVAILABLE"}))
            mutations.append(lambda c, key=name: c.pop(key))
        for index, mutate in enumerate(mutations):
            config = deepcopy(self.config)
            mutate(config)
            with self.subTest(index=index), self.assertRaises(contract.HostConfigurationError):
                contract.input_mode(config)

    def test_legacy_without_override_keeps_original_names(self):
        legacy = {"schemaVersion": 1, "activationProfile": contract.PROFILE,
                  "mode": "RESEARCH_ONLY", "runtimeIdentity": "production-continuous-runtime-v2",
                  "orderCapability": "UNAVAILABLE"}
        self.assertEqual(contract.validate_host(legacy)["services"], contract.service_names("production"))

    def test_binding_reference_is_part_of_existing_host_fingerprint(self):
        first = contract.host_fingerprint(self.config)
        self.config["qualificationServiceTargets"]["sha256"] = "b" * 64
        self.assertNotEqual(first, contract.host_fingerprint(self.config))
        with self.assertRaises(contract.HostConfigurationError):
            contract.validate_host(self.config)
