from __future__ import annotations

from .domain import MotionIntent
from .fast_path import FastPathInterpreter
from .ollama import OllamaInterpreter


class HybridInterpreter:
    def __init__(
        self,
        fast_path: FastPathInterpreter | None = None,
        ollama: OllamaInterpreter | None = None,
    ) -> None:
        self.fast_path = fast_path or FastPathInterpreter()
        self.ollama = ollama or OllamaInterpreter()

    def interpret(self, text: str) -> MotionIntent:
        intent = self.fast_path.interpret(text)
        return intent if intent is not None else self.ollama.interpret(text)
