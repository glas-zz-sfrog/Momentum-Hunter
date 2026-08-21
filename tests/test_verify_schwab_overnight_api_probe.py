from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools" / "verify_schwab_overnight_api_probe.py"
SPEC = importlib.util.spec_from_file_location("verify_schwab_overnight_api_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class VerifySchwabOvernightApiProbeTests(unittest.TestCase):
    def test_fingerprint_rejects_tampering(self) -> None:
        value = {"taskId": verify.TASK_ID, "count": 1}
        value["fingerprint"] = verify.fingerprint(value)
        verify.verify_fingerprint(value, "fingerprint")
        value["count"] = 2
        with self.assertRaisesRegex(verify.VerificationError, "did not verify"):
            verify.verify_fingerprint(value, "fingerprint")

    def test_parse_timestamp_requires_offset(self) -> None:
        parsed = verify.parse_timestamp("2026-08-21T02:30:00-04:00")
        self.assertEqual(datetime(2026, 8, 21, 6, 30, tzinfo=timezone.utc), parsed)
        with self.assertRaisesRegex(verify.VerificationError, "offset"):
            verify.parse_timestamp("2026-08-21T02:30:00")

    def test_expected_routes_have_no_account_or_order_endpoint(self) -> None:
        paths = {key[2] for key in verify.EXPECTED_ROUTES}
        self.assertFalse(any("account" in path.lower() for path in paths))
        self.assertFalse(any("order" in path.lower() for path in paths))


if __name__ == "__main__":
    unittest.main()
