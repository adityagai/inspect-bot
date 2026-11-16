"""Claude models for CrewAI agents.

CrewAI 1.15 decides image support from a hard-coded list that stops at Claude 4,
so Claude 5 models are refused for `input_files`. ClaudeLLM marks them as
image-capable; everything else is CrewAI's native Anthropic provider.
"""

from __future__ import annotations

import os

from crewai.llms.providers.anthropic.completion import AnthropicCompletion


class ClaudeLLM(AnthropicCompletion):
    def supports_multimodal(self) -> bool:  # every Claude 3+ model accepts images
        return True


def vision_llm(max_tokens: int = 1500) -> ClaudeLLM:
    return ClaudeLLM(model=os.getenv("INSPECTBOT_VISION_MODEL", "claude-sonnet-5-5"), max_tokens=max_tokens)


def text_llm(max_tokens: int = 1500) -> ClaudeLLM:
    return ClaudeLLM(model=os.getenv("INSPECTBOT_TEXT_MODEL", "claude-haiku-5-5"), max_tokens=max_tokens)


def verify_llm(max_tokens: int = 1500) -> ClaudeLLM:
    """The Verification agent is the critical judge, so it defaults to the stronger model."""
    return ClaudeLLM(model=os.getenv("INSPECTBOT_VERIFY_MODEL", os.getenv("INSPECTBOT_VISION_MODEL", "claude-sonnet-5-5")),
                     max_tokens=max_tokens)
