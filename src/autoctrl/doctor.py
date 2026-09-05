from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import json
import os
import subprocess


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    key: str
    label: str
    ok: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def failures(self) -> tuple[DoctorCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "checks": [check.to_dict() for check in self.checks],
        }


def build_doctor_report(
    *,
    ros_environment_ok: bool,
    ros_environment_detail: str,
    zenoh_bridge_ok: bool,
    zenoh_bridge_detail: str,
    model: str,
    model_ok: bool,
    model_detail: str,
    data_checks: tuple[DoctorCheck, ...] = (),
) -> DoctorReport:
    return DoctorReport(
        (
            DoctorCheck(
                key="ros2_environment",
                label="ROS2 環境",
                ok=ros_environment_ok,
                detail=ros_environment_detail,
            ),
            DoctorCheck(
                key="zenoh_bridge",
                label="Zenoh bridge 容器",
                ok=zenoh_bridge_ok,
                detail=zenoh_bridge_detail,
            ),
            DoctorCheck(
                key="model",
                label="本地模型",
                ok=model_ok,
                detail=model_detail or model,
            ),
        ) + data_checks
    )


def check_ros2_environment(
    environ: Mapping[str, str] | None = None,
) -> tuple[bool, str]:
    values = os.environ if environ is None else environ
    distro = values.get("ROS_DISTRO", "").strip()
    version = values.get("ROS_VERSION", "").strip()
    ament_prefix = values.get("AMENT_PREFIX_PATH", "").strip()
    ok = bool(distro and version == "2" and ament_prefix)
    if ok:
        return True, f"ROS_DISTRO={distro} · AMENT_PREFIX_PATH={ament_prefix}"
    return (
        False,
        "未偵測到完整 ROS2 source 環境"
        f" · ROS_DISTRO={distro or 'unset'}"
        f" · ROS_VERSION={version or 'unset'}",
    )


def check_zenoh_bridge(
    *,
    container_name: str = "zenoh-bridge",
    timeout_s: float = 2.0,
) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{json .State}}",
                container_name,
            ],
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return False, "找不到 docker 指令"
    except subprocess.TimeoutExpired:
        return False, f"{container_name} · Docker 檢查逾時"

    if completed.returncode != 0:
        reason = completed.stderr.strip().splitlines()
        detail = reason[-1] if reason else "找不到容器或無法連線 Docker"
        return False, f"{container_name} · {detail}"

    try:
        state = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return False, f"{container_name} · Docker 回傳無法解析"

    running = bool(state.get("Running")) and state.get("Status") == "running"
    health = state.get("Health", {}).get("Status")
    healthy = health in (None, "healthy")
    if running and healthy:
        suffix = "running" if health is None else f"running · {health}"
        return True, f"{container_name} · {suffix}"

    status = str(state.get("Status", "unknown"))
    if health:
        status += f" · {health}"
    return False, f"{container_name} · {status}"


def check_odom_freshness(
    *, key: str, label: str, topic: str, age_s: float | None, timeout_s: float,
) -> DoctorCheck:
    """A receipt-time check, not proof of bridge connectivity or vehicle motion."""
    if age_s is None:
        return DoctorCheck(key, label, False, f"{topic} · 尚未收到有效 odom；topic 存在不代表有資料")
    ok = age_s < timeout_s
    state = "最近有收到資料" if ok else "資料逾時；請檢查來源是否啟動／模擬是否播放及通訊"
    return DoctorCheck(key, label, ok,
        f"{topic} · {state} · 距上次接收 {age_s:.2f} 秒（門檻 {timeout_s:g} 秒）")
