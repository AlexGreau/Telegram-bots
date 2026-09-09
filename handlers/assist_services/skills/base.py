"""The Skill abstraction.

A Skill bundles everything one capability needs inside the /assist agent loop:
its tool schemas, the system-prompt instructions that explain when/how to use
them, and (for capabilities that go through a Confirm/Cancel step) how to preview
and commit a pending action. The registry in __init__.py collects these so
assist.py never has to special-case individual capabilities.
"""
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


def _no_instructions(ctx: dict) -> str:
    return ""


@dataclass
class Skill:
    name: str
    tools: list[dict]
    # async (tool_name, inputs, telegram_context) -> (result_for_claude, pending | None)
    execute: Callable[[str, dict, object], Awaitable[tuple[str, "dict | None"]]]
    # (ctx) -> system-prompt fragment for this capability
    instructions: Callable[[dict], str] = _no_instructions
    # (pending_item) -> the line shown in the "About to log:" confirmation card
    preview: Optional[Callable[[dict], str]] = None
    # (pending_item, telegram_context) -> (confirmation_text, history_outcome_text)
    commit: Optional[Callable[[dict, object], tuple[str, str]]] = None

    @property
    def tool_names(self) -> set[str]:
        return {t["name"] for t in self.tools}
