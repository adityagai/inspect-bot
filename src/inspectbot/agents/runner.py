"""How the Coordinator invokes an agent.

CrewAIRunner runs a real CrewAI Agent (Claude) with structured output and optional
image files. ScriptedRunner returns canned outputs, so the Flow's routing, guards
and stop rules can be tested without API calls.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

from inspectbot.agents.prompts import ROLES

T = TypeVar("T", bound=BaseModel)


class AgentRunner(Protocol):
    def run(self, role: str, prompt: str, schema: type[T], images: dict[str, str] | None = None) -> T: ...


class CrewAIRunner:
    """One CrewAI Agent per role, created lazily."""

    def __init__(self) -> None:
        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        self._agents: dict[str, object] = {}
        self.calls: list[dict] = []

    def _agent(self, role: str):
        if role not in self._agents:
            from crewai import Agent

            from inspectbot.agents.llm import text_llm, verify_llm, vision_llm

            llm = {"inspection": vision_llm, "baseline": vision_llm, "verification": verify_llm}.get(role, text_llm)()
            self._agents[role] = Agent(**ROLES[role], llm=llm, verbose=False, max_iter=3)
        return self._agents[role]

    def run(self, role: str, prompt: str, schema: type[T], images: dict[str, str] | None = None) -> T:
        kwargs = {}
        if images:
            from crewai_files import ImageFile

            kwargs["input_files"] = {name: ImageFile(source=path) for name, path in images.items()}
        last_error: Exception | None = None
        for _ in range(2):  # one retry on malformed structured output
            try:
                out = self._agent(role).kickoff(prompt, response_format=schema, **kwargs)
                result = out.pydantic if isinstance(out.pydantic, schema) else schema.model_validate_json(
                    out.raw[out.raw.find("{"): out.raw.rfind("}") + 1])
                break
            except Exception as e:  # noqa: BLE001 - surfaced after the retry
                last_error = e
        else:
            raise RuntimeError(f"{role} agent failed to return a valid {schema.__name__}: {last_error}")
        self.calls.append({"role": role, "schema": schema.__name__, "images": list(images or {})})
        return result


class ScriptedRunner:
    """Returns pre-programmed outputs per role, in order. A callable script receives the prompt."""

    def __init__(self, script: dict[str, list[BaseModel | Callable[[str], BaseModel]]]) -> None:
        self._queues = {role: deque(items) for role, items in script.items()}
        self.calls: dict[str, list[str]] = defaultdict(list)

    def run(self, role: str, prompt: str, schema: type[T], images: dict[str, str] | None = None) -> T:
        self.calls[role].append(prompt)
        queue = self._queues.get(role)
        if not queue:
            raise AssertionError(f"no scripted output left for role '{role}'")
        item = queue.popleft()
        out = item(prompt) if callable(item) else item
        assert isinstance(out, schema), f"{role}: scripted {type(out).__name__}, expected {schema.__name__}"
        return out
