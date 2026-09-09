"""Skill registry for the /assist agent loop.

Each capability (finance, flashcards, fitness) is a Skill that owns its own tool
schemas, prompt instructions, and preview/commit steps. assist.py collects them
through the helpers here and never special-cases an individual capability.
"""
from handlers.assist_services.skills.base import Skill
from handlers.assist_services.skills.finance.tools import FINANCE_SKILL
from handlers.assist_services.skills.flashcards import FLASHCARD_SKILL
from handlers.assist_services.skills.fitness import FITNESS_SKILL

SKILLS: list[Skill] = [FINANCE_SKILL, FLASHCARD_SKILL, FITNESS_SKILL]

ALL_TOOLS: list[dict] = [t for s in SKILLS for t in s.tools]


def build_skill_instructions(ctx: dict) -> str:
    """Concatenate every skill's system-prompt fragment."""
    return "".join(s.instructions(ctx) for s in SKILLS)


async def dispatch_tool(name: str, inputs: dict, context) -> tuple[str, dict | None]:
    """Route a tool call to the owning skill. Stamps pending items with the skill name."""
    for s in SKILLS:
        if name in s.tool_names:
            result, pending = await s.execute(name, inputs, context)
            if pending is not None:
                pending.setdefault("skill", s.name)
            return result, pending
    return f"Unknown tool: {name}", None


def preview_pending(item: dict) -> str:
    """The line shown in the 'About to log:' confirmation card for a pending item."""
    for s in SKILLS:
        if s.name == item.get("skill") and s.preview:
            return s.preview(item)
    return str(item)


def commit_pending(item: dict, context) -> tuple[str, str]:
    """Commit a confirmed pending item. Returns (confirmation_text, history_outcome_text)."""
    for s in SKILLS:
        if s.name == item.get("skill") and s.commit:
            return s.commit(item, context)
    raise ValueError(f"No commit handler for pending item (skill={item.get('skill')!r})")
