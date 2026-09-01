import math
import unittest

from autoctrl.domain import LinearDirection, MotionIntent, MotionKind, TurnDirection
from autoctrl.motion import MotionConfig, MotionController, Pose2D


class MotionControllerTests(unittest.TestCase):
    def test_timed_motion_stops_when_duration_expires(self) -> None:
        now = [10.0]
        controller = MotionController(clock=lambda: now[0])
        controller.start(
            MotionIntent(
                kind=MotionKind.ROTATE,
                turn_direction=TurnDirection.RIGHT,
                duration_s=2.0,
            ),
            None,
        )
        self.assertFalse(controller.tick(None).stopped)
        now[0] = 12.0
        self.assertTrue(controller.tick(None).stopped)
        self.assertIsNone(controller.active_intent)

    def test_continuous_forward_runs_until_stop(self) -> None:
        controller = MotionController(MotionConfig(linear_speed_mps=0.2))
        controller.start(
            MotionIntent(kind=MotionKind.MOVE_LINEAR, linear_direction=LinearDirection.FORWARD),
            None,
        )
        self.assertEqual(controller.tick(None).linear_x, 0.2)
        controller.stop()
        self.assertTrue(controller.tick(None).stopped)

    def test_distance_motion_stops_at_target(self) -> None:
        controller = MotionController()
        start = Pose2D(1.0, 2.0, 0.0)
        controller.start(
            MotionIntent(
                kind=MotionKind.MOVE_LINEAR,
                linear_direction=LinearDirection.BACKWARD,
                distance_m=0.5,
            ),
            start,
        )
        self.assertLess(controller.tick(start).linear_x, 0)
        self.assertTrue(controller.tick(Pose2D(1.5, 2.0, 0.0)).stopped)
        self.assertIsNone(controller.active_intent)

    def test_continuous_left_turn_is_an_ackermann_arc(self) -> None:
        controller = MotionController(
            MotionConfig(turn_linear_speed_mps=0.3, angular_speed_rps=0.5)
        )
        controller.start(
            MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.LEFT),
            None,
        )
        velocity = controller.tick(None)
        self.assertEqual(velocity.linear_x, 0.3)
        self.assertEqual(velocity.angular_z, 0.5)
        self.assertIsNotNone(controller.active_intent)

    def test_continuous_right_turn_has_negative_angular_velocity(self) -> None:
        controller = MotionController()
        controller.start(
            MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.RIGHT),
            None,
        )
        velocity = controller.tick(None)
        self.assertGreater(velocity.linear_x, 0)
        self.assertLess(velocity.angular_z, 0)

    def test_rotation_handles_yaw_wraparound(self) -> None:
        controller = MotionController()
        start = Pose2D(0, 0, math.radians(179))
        controller.start(
            MotionIntent(kind=MotionKind.ROTATE, turn_direction=TurnDirection.LEFT, angle_deg=5),
            start,
        )
        controller.tick(Pose2D(0, 0, math.radians(-179)))
        self.assertIsNotNone(controller.active_intent)
        velocity = controller.tick(Pose2D(0, 0, math.radians(-176)))
        self.assertTrue(velocity.stopped)
        self.assertIsNone(controller.active_intent)


if __name__ == "__main__":
    unittest.main()
