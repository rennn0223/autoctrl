import os
import pathlib
import unittest

import pexpect


class CtrlCExitTests(unittest.TestCase):
    def test_single_ctrl_c_exits_without_enter(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[1]
        child = pexpect.spawn(
            str(project / "scripts" / "autoctrl-ros"),
            [
                "--ros-args",
                "-p",
                "robot_namespace:=/ctrl_c_test",
                "-p",
                "doctor_startup_delay_s:=0.0",
                "-p",
                "doctor_timeout_s:=0.2",
            ],
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

    def test_doctor_ignores_missing_robot_and_cli_still_opens(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[1]
        child = pexpect.spawn(
            str(project / "scripts" / "autoctrl-ros"),
            [
                "--ros-args",
                "-p",
                "robot_namespace:=/doctor_missing_robot_test",
                "-p",
                "doctor_startup_delay_s:=0.0",
                "-p",
                "doctor_timeout_s:=0.2",
                "-p",
                "ollama_url:=http://127.0.0.1:9",
            ],
            cwd=str(project),
            encoding="utf-8",
            timeout=8,
        )
        try:
            child.expect("Doctor")
            child.expect("fail")
            child.expect("›")
            child.sendline("/doctor")
            child.expect("ROS2 環境")
            child.expect("Zenoh bridge")
            child.expect("›")
            child.sendcontrol("c")
            child.expect(pexpect.EOF, timeout=1)
        finally:
            if child.isalive():
                child.sendline("")
                child.close(force=True)

    def test_history_and_slash_menu_can_select_exit(self) -> None:
        project = pathlib.Path(__file__).resolve().parents[1]
        child = pexpect.spawn(
            str(project / "scripts" / "autoctrl-ros"),
            [
                "--ros-args",
                "-p",
                "robot_namespace:=/slash_history_test",
                "-p",
                "doctor_startup_delay_s:=0.0",
                "-p",
                "doctor_timeout_s:=0.2",
            ],
            cwd=str(project),
            env={**os.environ, "TERM": "xterm-256color"},
            encoding="utf-8",
            timeout=8,
        )
        try:
            child.expect("›")
            child.sendline("/doctor")
            child.expect("ROS2 環境")
            child.expect("›")

            child.send("\x1b[A")
            child.send("\r")
            child.expect("ROS2 環境")
            child.expect("›")

            child.send("/")
            child.expect("安全停止並離開")
            child.send("\x1b[B\x1b[B\x1b[B\x1b[B")
            child.send("\r")
            child.expect("AutoCtrl 已安全停止")
            child.expect(pexpect.EOF, timeout=1)
        finally:
            if child.isalive():
                child.sendline("")
                child.close(force=True)


if __name__ == "__main__":
    unittest.main()
