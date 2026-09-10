"""Opt-in odometry navigation experiments. No obstacle avoidance or real-car output."""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from .motion import Pose2D, PoseFeedback


@dataclass(frozen=True)
class Point:
    x: float
    y: float


def relative_points(points: list[Point], origin: Pose2D) -> list[Point]:
    c, s = math.cos(origin.yaw), math.sin(origin.yaw)
    return [Point(origin.x + c*p.x - s*p.y, origin.y + s*p.x + c*p.y) for p in points]


def figure_eight(radius: float = 0.8, samples: int = 120) -> list[Point]:
    if not math.isfinite(radius) or radius < 0.5 or samples < 40:
        raise ValueError('radius must be >= 0.5 m and samples >= 40')
    return [Point(radius*math.sin(t), sign*radius*(1-math.cos(t)))
            for sign in (1, -1)
            for i in range(1, samples+1)
            for t in [2*math.pi*i/samples]]


class Tracker:
    """Ordered target pursuit; never chooses a later branch at a crossing."""
    def __init__(self, points: list[Point], *, dense: bool = False, speed: float = 0.3):
        if not points or any(not math.isfinite(v) for p in points for v in (p.x, p.y)):
            raise ValueError('finite, nonempty waypoints required')
        if not math.isfinite(speed) or not 0 < speed <= 0.4:
            raise ValueError('speed must be in (0, 0.4] m/s')
        self.points, self.dense, self.speed = points, dense, speed
        self.index = 0
        self.reached: list[dict] = []

    @property
    def done(self) -> bool:
        return self.index == len(self.points)

    def tick(self, pose: Pose2D) -> tuple[float, float]:
        if not all(math.isfinite(v) for v in (pose.x, pose.y, pose.yaw)):
            raise ValueError('invalid pose')
        while not self.done:
            p = self.points[self.index]
            distance = math.hypot(p.x-pose.x, p.y-pose.y)
            tolerance = 0.22 if self.dense and self.index < len(self.points)-1 else 0.10
            if distance > tolerance:
                break
            self.reached.append({'index': self.index, 'error_m': distance})
            self.index += 1
        if self.done:
            return 0., 0.
        dx, dy = p.x-pose.x, p.y-pose.y
        lateral = -math.sin(pose.yaw)*dx + math.cos(pose.yaw)*dy
        curvature = 2*lateral/max(distance*distance, 0.01)
        steering = max(-0.55, min(0.55, math.atan(0.24*curvature)))
        speed = min(self.speed, max(0.10, distance*0.8))
        return speed, steering


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=['waypoints', 'figure8'])
    parser.add_argument('--points', default='[[0.7,0],[1.4,0.3]]', help='ordered JSON [x,y] pairs in metres')
    parser.add_argument('--frame', choices=['relative', 'odom'], default='relative')
    parser.add_argument('--radius', type=float, default=0.8)
    parser.add_argument('--speed', type=float, default=0.3)
    parser.add_argument('--timeout', type=float, default=300.)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be positive and finite')
    points = figure_eight(args.radius) if args.task == 'figure8' else [Point(*p) for p in json.loads(args.points)]
    Tracker(points, speed=args.speed)  # Validate before connecting or publishing.
    import rclpy
    from rclpy.qos import qos_profile_sensor_data
    from rclpy.signals import SignalHandlerOptions
    from nav_msgs.msg import Odometry
    from ackermann_msgs.msg import AckermannDriveStamped
    # Keep the ROS context alive until the Ctrl+C zero-speed cleanup finishes.
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node('autoctrl_navigation_experiment')
    feedback = PoseFeedback(timeout_s=1.)
    frames = set()
    def odom(msg):
        frames.add((msg.header.frame_id, msg.child_frame_id))
        q, p = msg.pose.pose.orientation, msg.pose.pose.position
        feedback.update(Pose2D(p.x, p.y, math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))))
    node.create_subscription(Odometry, '/sim/odom', odom, qos_profile_sensor_data)
    pub = node.create_publisher(AckermannDriveStamped, '/sim/ackermann_cmd', 10)
    def publish(speed=0., steering=0.):
        msg = AckermannDriveStamped()
        msg.header.stamp = node.get_clock().now().to_msg()
        msg.drive.speed, msg.drive.steering_angle = float(speed), float(steering)
        msg.drive.acceleration, msg.drive.steering_angle_velocity = .5, .5
        pub.publish(msg)
    result = {'task': args.task, 'frame': args.frame, 'state': 'aborted', 'samples': []}
    tracker = None
    started = time.monotonic()
    try:
        while feedback.current() is None and time.monotonic()-started < 10:
            rclpy.spin_once(node, timeout_sec=.1)
        origin = feedback.current()
        if origin is None:
            raise RuntimeError('no fresh simulation odometry')
        if args.frame == 'relative':
            points = relative_points(points, origin)
        tracker = Tracker(points, dense=args.task == 'figure8', speed=args.speed)
        result['targets'] = [[p.x, p.y] for p in points]
        result['origin'] = [origin.x, origin.y, origin.yaw]
        started = time.monotonic()
        last_print = -10.
        while not tracker.done:
            rclpy.spin_once(node, timeout_sec=.05)
            elapsed = time.monotonic()-started
            pose = feedback.current()
            if pose is None:
                raise RuntimeError('odometry stale: motion cancelled')
            if len(frames) != 1:
                raise RuntimeError('odometry frame changed')
            if elapsed > args.timeout:
                raise RuntimeError('navigation timeout')
            speed, steering = tracker.tick(pose)
            publish(speed, steering)
            result['samples'].append([elapsed, pose.x, pose.y, pose.yaw, tracker.index, speed, steering])
            if elapsed-last_print >= 10:
                print(f'{elapsed:.1f}s target {tracker.index}/{len(points)} pose ({pose.x:.2f}, {pose.y:.2f})', flush=True)
                last_print = elapsed
            time.sleep(.02)
        result['state'] = 'completed'
    except (KeyboardInterrupt, RuntimeError, ValueError) as exc:
        result['reason'] = str(exc) or 'interrupted'
    finally:
        stop_pose = feedback.current()
        for _ in range(10):
            publish()
            rclpy.spin_once(node, timeout_sec=.03)
            time.sleep(.02)
        result['elapsed_s'] = time.monotonic()-started
        result['reached'] = tracker.reached if tracker else []
        final = feedback.current()
        if final and tracker:
            result['final_pose'] = [final.x, final.y, final.yaw]
            if stop_pose:
                result['stopping_drift_m'] = math.hypot(final.x-stop_pose.x, final.y-stop_pose.y)
            result['endpoint_error_m'] = math.hypot(final.x-points[-1].x, final.y-points[-1].y)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n')
        node.destroy_node()
        rclpy.shutdown()
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples', 'targets', 'reached')}, indent=2))
    return 0 if result['state'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
