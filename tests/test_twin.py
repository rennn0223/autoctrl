import math
import unittest

from autoctrl.motion import Pose2D
from autoctrl.twin import TwinMonitor


class TwinMonitorTests(unittest.TestCase):
    def test_reports_relative_displacement_and_heading_error(self) -> None:
        monitor = TwinMonitor()
        monitor.update_real(Pose2D(10.0, 5.0, math.radians(170)))
        monitor.update_simulation(Pose2D(-2.0, 4.0, math.radians(-170)))
        monitor.reset()

        monitor.update_real(Pose2D(11.0, 5.0, math.radians(-170)))
        monitor.update_simulation(Pose2D(-0.8, 4.0, math.radians(-145)))
        report = monitor.report()

        self.assertTrue(report["available"])
        self.assertAlmostEqual(report["real_displacement_m"], 1.0)
        self.assertAlmostEqual(report["simulation_displacement_m"], 1.2)
        self.assertAlmostEqual(report["displacement_error_m"], 0.2)
        self.assertAlmostEqual(report["real_yaw_delta_deg"], 20.0)
        self.assertAlmostEqual(report["simulation_yaw_delta_deg"], 25.0)
        self.assertAlmostEqual(report["heading_error_deg"], 5.0)

    def test_missing_side_is_unavailable(self) -> None:
        monitor = TwinMonitor()
        monitor.update_real(Pose2D(0.0, 0.0, 0.0))
        self.assertFalse(monitor.report()["available"])


if __name__ == "__main__":
    unittest.main()
