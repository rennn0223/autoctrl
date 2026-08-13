from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import LinearDirection, MotionIntent, MotionKind, TurnDirection


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
        transport: Transport | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._transport = transport or self._http_transport

    def interpret(self, text: str) -> MotionIntent:
        payload = {
            "model": self.model,
            "stream": False,
            "think": False,
            "keep_alive": -1,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是台灣自動化展小車的移動命令解析器。只解析使用者想要的移動，不要自行產生底盤速度。"
                        "前進或後退未指定距離代表持續移動，直到使用者說停止；此時省略 distance_m。"
                        "左轉或右轉未指定角度時省略 angle_deg，代表沿弧線持續轉彎直到使用者說停止。"
                        "命令不清楚、互相矛盾或不是車輛移動時，不要呼叫工具，簡短說明需要澄清。"
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
            detail = str(message.get("content") or "模型沒有產生可執行命令")
            raise InterpretationError(detail)

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
                "messages": [{"role": "user", "content": "只回答 ready"}],
            }
        )

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
    def _to_intent(name: str, args: dict[str, Any], text: str) -> MotionIntent:
        try:
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
