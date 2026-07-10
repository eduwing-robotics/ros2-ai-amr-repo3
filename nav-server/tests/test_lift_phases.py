"""Lift phase height planning tests."""
import unittest

from nav_app.services.lift_phases import (
    resolve_carry_height_mm,
    resolve_post_insert_height_mm,
    resolve_pre_insert_height_mm,
)

ROBOT_LIFT_CONFIG = {
    "load_height_mm": 43.0,
    "carry_height_mm": 50.0,
    "unload_height_mm": 6.0,
    "levels": {
        "1": {"load_height_mm": 43.0, "unload_height_mm": 6.0},
        "2": {"load_height_mm": 50.0, "unload_height_mm": 6.0},
    },
}


class LiftPhaseTests(unittest.TestCase):
    def test_floor_load_no_pre_insert(self):
        self.assertIsNone(resolve_pre_insert_height_mm("load", 1, {}, ROBOT_LIFT_CONFIG))
        self.assertAlmostEqual(resolve_post_insert_height_mm("load", 1, {}, ROBOT_LIFT_CONFIG), 43.0)

    def test_level2_pre_insert_before_insert(self):
        self.assertAlmostEqual(
            resolve_pre_insert_height_mm("unload", 2, {}, ROBOT_LIFT_CONFIG),
            50.0,
        )
        self.assertAlmostEqual(
            resolve_pre_insert_height_mm("load", 2, {}, ROBOT_LIFT_CONFIG),
            50.0,
        )

    def test_carry_after_load_level1(self):
        self.assertAlmostEqual(
            resolve_carry_height_mm("load", 1, {}, ROBOT_LIFT_CONFIG),
            50.0,
        )
        self.assertIsNone(resolve_carry_height_mm("unload", 1, {}, ROBOT_LIFT_CONFIG))

    def test_carry_disabled(self):
        self.assertIsNone(
            resolve_carry_height_mm("load", 1, {"carry_after_load": False}, ROBOT_LIFT_CONFIG)
        )

    def test_slot_pre_insert_override(self):
        payload = {"pre_insert_mm": 45.0}
        self.assertAlmostEqual(
            resolve_pre_insert_height_mm("load", 1, payload, ROBOT_LIFT_CONFIG),
            45.0,
        )

    def test_unload_post_insert(self):
        self.assertAlmostEqual(
            resolve_post_insert_height_mm("unload", 2, {}, ROBOT_LIFT_CONFIG),
            6.0,
        )


if __name__ == "__main__":
    unittest.main()
