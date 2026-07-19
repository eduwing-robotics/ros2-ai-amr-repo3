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


class LiftClientArrivalTests(unittest.TestCase):
    def _client_at(self, position_mm: float) -> LiftClient:
        client = LiftClient(MagicMock(), {"enabled": False, "position_tolerance_mm": 2.0})
        client.position_mm = position_mm
        client.direction = "STOP"
        client.move_to = MagicMock(return_value={"position_mm": position_mm, "direction": "STOP"})
        return client

    def test_force_move_at_zero_returns_immediately_when_already_arrived(self):
        client = self._client_at(0.0)

        result = client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)

        self.assertEqual(result["position_mm"], 0.0)
        client.move_to.assert_not_called()

    def test_arrival_tolerance_boundary_is_inclusive_even_when_forced(self):
        for position_mm in (1.9, 2.0):
            with self.subTest(position_mm=position_mm):
                client = self._client_at(position_mm)
                client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)
                client.move_to.assert_not_called()

    def test_position_outside_tolerance_still_executes_move(self):
        client = self._client_at(2.1)

        client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)

        client.move_to.assert_called_once_with(0.0, timeout_sec=None, tolerance_mm=2.0)


if __name__ == "__main__":
    unittest.main()
