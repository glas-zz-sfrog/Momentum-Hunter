from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from momentum_hunter import continuous_host_contract as contract
from tests.test_continuous_host_boundaries import configuration, seal, save_config


class DirectScienceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="MH-014A-Contract-")
        self.addCleanup(self.temp.cleanup)
        self.config = configuration(Path(self.temp.name))

    def test_native_service_sid_matches_observed_sc_showsid(self):
        self.assertEqual(contract.science_service_sid("qual-013b-r011-214611"),
            "S-1-5-80-2360323399-3885101186-852604897-3857439045-1863769236")
        self.assertNotEqual(contract.science_sid("qual-013b"), contract.science_service_sid("qual-013b"))

    def test_legacy_synthetic_restrictor_cannot_select_direct_service(self):
        self.config["host"]["science"]["restrictingSid"] = contract.science_sid("qual-013b")
        seal(self.config)
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config)

    def test_model_manifest_and_principal_are_bound(self):
        for key, value in (("hostingModel", "CHILD"), ("imageManifestSha256", ""),
                           ("imageManifestSha256", None), ("principal", "NT AUTHORITY\\SYSTEM")):
            config = deepcopy(self.config)
            config["host"]["science"][key] = value
            seal(config)
            with self.subTest(key=key), self.assertRaises(contract.HostConfigurationError): contract.validate_host(config)

    def test_plan_exact_config_not_shared_secret_directory(self):
        path = save_config(self.config)
        plan = contract.install_plan(self.config, path, Path(self.temp.name) / "donor", Path("python.exe"))
        permission = plan["permissions"]
        self.assertEqual(permission["configuration"]["path"], str(path))
        self.assertFalse(permission["configuration"]["directoryRead"])
        self.assertFalse(permission["writerKey"]["read"])
        self.assertEqual(permission["scienceServiceGeneration"]["path"], str(Path(self.config["hostStateRoot"]) / "science"))
        science = plan["services"][1]
        self.assertEqual(science["hostingModel"], contract.SCM_DIRECT)
        self.assertEqual(science["requiredPrivileges"], ["SeChangeNotifyPrivilege"])
        self.assertEqual(science["serviceSidType"], "RESTRICTED")
        self.assertFalse(science["productionServiceDenial"]["applicationAuthorizedByPlan"])
        self.assertFalse(plan["windowsMutation"])

    def test_config_cannot_be_the_secret_key(self):
        path = Path(self.config["ipcKeyPath"])
        with self.assertRaises(contract.HostConfigurationError): contract.validate_host(self.config, path)
