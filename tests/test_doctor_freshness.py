import pytest

from autoctrl.doctor import check_odom_freshness
from autoctrl.motion import Pose2D, PoseFeedback


@pytest.mark.parametrize("age,ok", [(None, False), (0.0, True), (0.99, True), (1.0, False), (20.0, False)])
def test_receipt_freshness(age, ok):
    check = check_odom_freshness(key="real_odom", label="實車 odom",
        topic="/custom/odom", age_s=age, timeout_s=1.0)
    assert check.ok is ok
    assert "/custom/odom" in check.detail


def test_stationary_pose_refreshes_receipt_age():
    now = [0.0]
    feedback = PoseFeedback(clock=lambda: now[0])
    assert feedback.age_s is None
    pose = Pose2D(0, 0, 0)
    feedback.update(pose)
    now[0] = 2.0
    assert feedback.age_s == 2.0
    assert feedback.current() is None
    feedback.update(pose)
    assert feedback.age_s == 0
    assert feedback.current() == pose
    feedback.update(Pose2D(float("nan"), 0, 0))
    assert feedback.age_s is None
