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

    def test_forced_home_move_is_arrived_at_zero_without_fresh_feedback(self):
        client = self._client()
        client.position_mm = 0.0
        client.direction = "STOP"
        client.move_to = MagicMock(side_effect=AssertionError("home no-op must not be sent"))

        result = client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)

        self.assertEqual(result["position_mm"], 0.0)
        client.move_to.assert_not_called()

    def test_forced_home_move_accepts_tolerance_boundary(self):
        for position in (1.9, 2.0):
            with self.subTest(position=position):
                client = self._client()
                client.position_mm = position
                client.direction = "STOP"
                client.move_to = MagicMock(side_effect=AssertionError("in-tolerance home must not move"))

                result = client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)

                self.assertEqual(result["position_mm"], position)
                client.move_to.assert_not_called()

    def test_forced_nonhome_noop_stops_stale_direction_without_waiting_for_feedback(self):
        client = self._client(1.282)
        client.position_mm = 8.0
        client.direction = "UP"
        client._publish_stop = MagicMock()
        client.move_to = MagicMock(side_effect=AssertionError("in-tolerance no-op must not move"))

        result = client.move_to_if_needed(6.0, tolerance_mm=2.0, force=True)

        self.assertEqual(result["position_mm"], 8.0)
        client._publish_stop.assert_called_once_with()
        client.move_to.assert_not_called()

    def test_forced_home_move_outside_tolerance_still_executes(self):
        client = self._client()
        client.position_mm = 2.1
        client.direction = "STOP"
        client.move_to = MagicMock(return_value={"position_mm": 0.0, "direction": "STOP"})

        result = client.move_to_if_needed(0.0, tolerance_mm=2.0, force=True)

        self.assertEqual(result["position_mm"], 0.0)
        client.move_to.assert_called_once_with(0.0, timeout_sec=None, tolerance_mm=2.0)


if __name__ == "__main__":
    unittest.main()
