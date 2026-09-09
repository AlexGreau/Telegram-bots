"""Language-flashcard capability inside the /assist agent loop.

Add words, run spaced-repetition quiz sessions, show deck stats. These tools
execute immediately (no Confirm/Cancel step), so this skill has no preview/commit.
"""
from handlers.assist_services.flashcards_db import add_card, get_due_cards, get_stats, init_db, update_card
from handlers.assist_services.skills.base import Skill

init_db()

FLASHCARD_TOOLS = [
    {
        "name": "add_flashcard",
        "description": (
            "Save a new word to the flashcard deck. Use when the user wants to memorise a word. "
            "Generate a natural example sentence if the user did not provide one."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "word":        {"type": "string", "description": "The word in the target language."},
                "translation": {"type": "string", "description": "Translation in the user's language."},
                "pinyin":      {"type": "string", "description": "Romanised pronunciation (for Chinese)."},
                "example":     {"type": "string", "description": "Short example sentence using the word."},
            },
            "required": ["word", "translation"],
        },
    },
    {
        "name": "get_due_cards",
        "description": (
            "Fetch flashcards due for review today. Call this to start a quiz session. "
            "Work through all returned cards one at a time, vary how you ask each question "
            "(translation, pinyin recall, fill-in-the-blank), grade generously for minor typos, "
            "and call update_flashcard after every answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max cards to fetch (default 10)."},
            },
        },
    },
    {
        "name": "update_flashcard",
        "description": "Record whether the user answered a card correctly. Call after grading each answer during a quiz.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card id from get_due_cards."},
                "correct": {"type": "boolean", "description": "True if the user answered correctly."},
            },
            "required": ["card_id", "correct"],
        },
    },
    {
        "name": "get_flashcard_stats",
        "description": "Return statistics about the flashcard deck. Use when the user asks about their progress.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _run(name: str, inputs: dict) -> str:
    if name == "add_flashcard":
        card_id = add_card(
            word=inputs["word"],
            translation=inputs["translation"],
            pinyin=inputs.get("pinyin"),
            example=inputs.get("example"),
        )
        return f"Card saved (id={card_id})."

    if name == "get_due_cards":
        cards = get_due_cards(inputs.get("limit", 10))
        if not cards:
            return "No cards due for review today."
        return str(cards)

    if name == "update_flashcard":
        result = update_card(inputs["card_id"], inputs["correct"])
        return str(result)

    if name == "get_flashcard_stats":
        return str(get_stats())

    return f"Unknown flashcard tool: {name}"


async def _execute(name: str, inputs: dict, context) -> tuple[str, dict | None]:
    return _run(name, inputs), None


def _instructions(ctx: dict) -> str:
    return (
        "You can manage a language flashcard deck: add new words, run quiz sessions, and show stats. "
        "When quizzing, work through all due cards one at a time, vary how you ask each question, "
        "grade generously for minor typos, and call update_flashcard after every answer. "
    )


FLASHCARD_SKILL = Skill(
    name="flashcards",
    tools=FLASHCARD_TOOLS,
    execute=_execute,
    instructions=_instructions,
)
