from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import (
    CommandRequest,
    ConversationReply,
    LinearDirection,
    MotionIntent,
    MotionKind,
    StatusKind,
    StatusQuery,
    TurnDirection,
)


class InterpretationError(RuntimeError):
    pass


Transport = Callable[[dict[str, Any]], dict[str, Any]]


class OllamaInterpreter:
    def __init__(
        self,
        *,
        model: str = "qwen3.6:35b",
        base_url: str = "http://127.0.0.1:11434",
        timeout_s: float = 120,
        temperature: float = 0.0,
        seed: int = 42,
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.seed = seed
        self._transport = transport or self._http_transport

    def interpret(self, text: str) -> CommandRequest:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "options": {"temperature": self.temperature, "seed": self.seed},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是台灣自動化展小車的移動命令解析器。只解析使用者想要的移動，不要自行產生底盤速度。"
                        "前進或後退未指定距離代表持續移動，直到使用者說停止；此時省略 distance_m。"
                        "左轉或右轉未指定角度時省略 angle_deg，代表沿弧線持續轉彎直到使用者說停止。"
                        "使用者詢問 ROS topics、目前位置或電池電壓時，呼叫對應的唯讀查詢工具。"
                        "一次只選擇一個最符合使用者主要意圖的工具。"
                        "若只是問候或一般聊天，請簡短自然回覆，不要呼叫任何工具。"
                        "系統不具備目的地導航或燈光控制；遇到此類要求不得改用狀態查詢或移動工具。"
                        "輸入不清楚、互相矛盾，或既不是車輛移動也不是上述狀態查詢時，"
                        "不要呼叫工具，簡短說明需要澄清。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            "tools": _TOOLS,
        }
        response = self._transport(payload)
        message = response.get("message", {})
        calls = message.get("tool_calls") or []
        if not calls:
            content = str(message.get("content") or "").strip()
            if content:
                return ConversationReply(
                    content=content,
                    source="ollama",
                    original_text=text,
                )
            raise InterpretationError("模型既沒有產生回覆，也沒有呼叫工具")
        if len(calls) != 1:
            raise InterpretationError("一次只能執行一個移動命令或狀態查詢")

        function = calls[0].get("function", {})
        name = function.get("name")
        arguments = function.get("arguments", {})
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, dict):
            raise InterpretationError("模型工具參數格式錯誤")
        return self._to_intent(name, arguments, text)

    def warmup(self) -> None:
        self._transport(
            {
                "model": self.model,
                "stream": False,
                "think": False,
                "keep_alive": -1,
                "options": {"temperature": self.temperature, "seed": self.seed},
                "messages": [{"role": "user", "content": "只回答 ready"}],
            }
        )

    def check_ready(self, *, timeout_s: float = 2.0) -> tuple[bool, str]:
        request = Request(
            f"{self.base_url}/api/show",
            data=json.dumps({"model": self.model}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_s) as response:
                response.read()
        except (HTTPError, URLError, TimeoutError) as exc:
            return False, f"{self.model} · 無法使用（{exc}）"
        return True, f"{self.model} · 已就緒"

    def _http_transport(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise InterpretationError(f"Ollama 呼叫失敗: {exc}") from exc

    @staticmethod
    def _to_intent(name: str, args: dict[str, Any], text: str) -> CommandRequest:
        try:
            status_tools = {
                "query_ros_topics": StatusKind.ROS_TOPICS,
                "query_robot_pose": StatusKind.ROBOT_POSE,
                "query_battery_voltage": StatusKind.BATTERY_VOLTAGE,
            }
            if name in status_tools:
                return StatusQuery(
                    kind=status_tools[name],
                    source="ollama",
                    original_text=text,
                )
            if name == "stop_vehicle":
                return MotionIntent.stop(source="ollama", original_text=text)
            if name == "move_linear":
                return MotionIntent(
                    kind=MotionKind.MOVE_LINEAR,
                    linear_direction=LinearDirection(args["direction"]),
                    distance_m=_optional_float(args, "distance_m"),
                    speed_mps=_optional_float(args, "speed_mps"),
                    source="ollama",
                    original_text=text,
                )
            if name == "rotate_vehicle":
                return MotionIntent(
                    kind=MotionKind.ROTATE,
                    turn_direction=TurnDirection(args["direction"]),
                    angle_deg=_optional_float(args, "angle_deg"),
                    angular_speed_rps=_optional_float(args, "angular_speed_rps"),
                    source="ollama",
                    original_text=text,
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise InterpretationError(f"模型工具參數無效: {exc}") from exc
        raise InterpretationError(f"未知工具: {name}")


def _optional_float(values: dict[str, Any], key: str) -> float | None:
    value = values.get(key)
    return None if value is None else float(value)


_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_ros_topics",
            "description": "唯讀查詢目前設定之機器人 namespace 下的 ROS 2 topics 與訊息型別。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_robot_pose",
            "description": "唯讀查詢小車目前在 odom 座標系中的 x、y 位置與朝向。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_battery_voltage",
            "description": "唯讀查詢小車目前回報的電池電壓；不推測未校正的電量百分比。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_linear",
            "description": "讓小車直線前進或後退。沒有指定距離時，省略 distance_m，代表持續移動直到停止命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["forward", "backward"]},
                    "distance_m": {"type": "number", "exclusiveMinimum": 0},
                    "speed_mps": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rotate_vehicle",
            "description": "讓阿克曼小車沿弧線左轉或右轉，會同時向前移動。沒有指定角度時省略 angle_deg，代表持續轉彎直到停止命令。",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["left", "right"]},
                    "angle_deg": {"type": "number", "exclusiveMinimum": 0},
                    "angular_speed_rps": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["direction"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_vehicle",
            "description": "立即停止小車目前的移動。",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
]
