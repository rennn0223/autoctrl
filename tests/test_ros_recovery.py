"""Keep ROS imports isolated from the parser-only benchmark tests."""
import os
from pathlib import Path
import subprocess

import pytest


def test_ros_recovery_in_isolated_process():
    setup = Path(os.environ.get("AUTOCTRL_ROS_SETUP", "/opt/ros/jazzy/setup.bash"))
    if not setup.is_file():
        pytest.skip("ROS 2 environment is not installed")
    project = Path(__file__).parents[1]
    result = subprocess.run(
        ["bash", "-c", 'source "$1" && uv run python -m pytest tests/ros_recovery_cases.py -q',
         "ros-recovery", str(setup)],
        cwd=project,
        env={**os.environ, "ROS_DOMAIN_ID": "201", "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
