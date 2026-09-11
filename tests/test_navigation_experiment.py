import math

import pytest
from autoctrl.motion import Pose2D
from autoctrl.navigation_experiment import Point, Tracker, figure_eight, relative_points


def test_relative_frame_rotates_and_translates():
    assert relative_points([Point(1, 0)], Pose2D(2, 3, math.pi/2))[0] == Point(2, 4)


@pytest.mark.parametrize('dense', [False, True])
def test_bicycle_reaches_all_targets_in_order(dense):
    points = figure_eight() if dense else [Point(.7, 0), Point(1.4, .3)]
    tracker = Tracker(points, dense=dense)
    pose = Pose2D(0, 0, 0)
    for _ in range(20000):
        speed, steering = tracker.tick(pose)
        if tracker.done:
            break
        dt = .02
        pose = Pose2D(pose.x+speed*math.cos(pose.yaw)*dt,
                      pose.y+speed*math.sin(pose.yaw)*dt,
                      pose.yaw+speed/.24*math.tan(steering)*dt)
    assert tracker.done
    assert [p['index'] for p in tracker.reached] == list(range(len(points)))
    assert math.hypot(pose.x-points[-1].x, pose.y-points[-1].y) <= .1
    assert tracker.tick(pose) == (0., 0.)


def test_crossing_does_not_skip_first_loop():
    tracker = Tracker(figure_eight(), dense=True)
    tracker.tick(Pose2D(0, 0, 0))
    assert tracker.index < 10


@pytest.mark.parametrize('points', [[], [Point(float('nan'), 0)], [Point(0, float('inf'))]])
def test_invalid_paths_rejected(points):
    with pytest.raises(ValueError):
        Tracker(points)


def test_steering_and_speed_bounded():
    speed, steering = Tracker([Point(0, 1)]).tick(Pose2D(0, 0, 0))
    assert 0 < speed <= .3
    assert abs(steering) <= .55
