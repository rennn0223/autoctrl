import pathlib
import unittest

import pexpect


class CtrlCExitTests(unittest.TestCase):
    def test_single_ctrl_c_exits_without_enter(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[1]
        child = pexpect.spawn(
            str(project / "scripts" / "autoctrl-ros"),
            ["--ros-args", "-p", "robot_namespace:=/ctrl_c_test"],
            cwd=str(project),
            encoding="utf-8",
            timeout=5,
        )
        try:
            child.expect("›")
            child.sendcontrol("c")
            child.expect(pexpect.EOF, timeout=1)
        finally:
            if child.isalive():
                child.sendline("")
                child.close(force=True)


if __name__ == "__main__":
    unittest.main()
