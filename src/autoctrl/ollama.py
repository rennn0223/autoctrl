from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .domain import CommandRequest, ConversationReply
from .skills import SkillError, SkillPolicy, SkillRegistry, SkillRisk


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
        skills: SkillRegistry | None = None,
        skill_policy: SkillPolicy | None = None,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.temperature = temperature
        self.seed = seed
        self._transport = transport or self._http_transport
        self._skills = skills or SkillRegistry.builtins()
        self._skill_policy = skill_policy or SkillPolicy.allow_all()
        self._skills.validate_policy(self._skill_policy)
        stop = next(
            (spec for spec in self._skills.specs if spec.name == "stop_vehicle"),
            None,
        )
        if stop is None or stop.risk is not SkillRisk.MOTION_CRITICAL:
            raise ValueError(
                "Skill Registry 必須包含 motion_critical 的 stop_vehicle"
            )

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
                        "若指定執行秒數，使用 duration_s，且不可同時指定 distance_m。"
                        "左轉或右轉未指定角度時省略 angle_deg，代表沿弧線持續轉彎直到使用者說停止。"
                        "轉向若指定執行秒數，使用 duration_s，且不可同時指定 angle_deg。"
                        "使用者詢問 ROS topics、目前位置、電池電壓或虛實同動差異時，呼叫對應的唯讀查詢工具。"
                        "一次只選擇一個最符合使用者主要意圖的工具。"
                        "若只是問候或一般聊天，請簡短自然回覆，不要呼叫任何工具。"
                        "系統不具備目的地導航或燈光控制；遇到此類要求不得改用狀態查詢或移動工具。"
                        "輸入不清楚、互相矛盾，或既不是車輛移動也不是上述狀態查詢時，"
                        "不要呼叫工具，簡短說明需要澄清。"
                    ),
                },
                {"role": "user", "content": text},
            ],
            "tools": self._skills.ollama_tools(self._skill_policy),
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
        try:
            return self._skills.resolve(
                str(name), arguments, text, self._skill_policy
            )
        except SkillError as exc:
            raise InterpretationError(str(exc)) from exc

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
