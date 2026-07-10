"""LiftClient command scaling tests."""
import unittest
from unittest.mock import MagicMock

from nav_app.services.lift_client import LiftClient


class LiftClientScaleTests(unittest.TestCase):
    def _client(self, scale: float = 1.0) -> LiftClient:
        node = MagicMock()
        return LiftClient(node, {"enabled": False, "command_scale": scale})

    def test_default_scale_is_identity(self):
        client = LiftClient(MagicMock(), {"enabled": False})
        self.assertAlmostEqual(client._command_scale(), 1.0)
        self.assertAlmostEqual(client._firmware_command_mm(50.0), 50.0)

    def test_tb3_2_calibration_scale(self):
        client = self._client(1.282)
        self.assertAlmostEqual(client._firmware_command_mm(50.0), 64.1)
        self.assertAlmostEqual(client._firmware_command_mm(43.0), 55.126)

    def test_at_target_accepts_logical_or_firmware_position(self):
        client = self._client(1.282)
        client.position_mm = 50.0
        self.assertTrue(client._at_target_mm(50.0, 2.0))
        client.position_mm = 64.0
        self.assertTrue(client._at_target_mm(50.0, 2.0))
        client.position_mm = 55.0
        self.assertTrue(client._at_target_mm(43.0, 2.0))
        client.position_mm = 30.0
        self.assertFalse(client._at_target_mm(50.0, 2.0))


if __name__ == "__main__":
    unittest.main()
