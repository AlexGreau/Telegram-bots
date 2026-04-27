import os
import sqlite3
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "flashcards.db")

# Days to next review indexed by streak (0=new/failed, 1,2,3,4,5+=mastered)
_INTERVALS = [1, 3, 7, 14, 30, 60]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                word             TEXT NOT NULL,
                translation      TEXT NOT NULL,
                pinyin           TEXT,
                example          TEXT,
                created_at       TEXT NOT NULL,
                streak           INTEGER DEFAULT 0,
                next_review      TEXT NOT NULL,
                total_attempts   INTEGER DEFAULT 0,
                correct_attempts INTEGER DEFAULT 0
            )
        """)


def add_card(word: str, translation: str, pinyin: str = None, example: str = None) -> int:
    today = date.today().isoformat()
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO cards (word, translation, pinyin, example, created_at, next_review) VALUES (?,?,?,?,?,?)",
            (word, translation, pinyin, example, today, today),
        )
        return cur.lastrowid


def get_due_cards(limit: int = 10) -> list[dict]:
    today = date.today().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM cards WHERE next_review <= ? ORDER BY next_review ASC LIMIT ?",
            (today, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def update_card(card_id: int, correct: bool) -> dict:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return {"error": "Card not found"}

        new_streak = (row["streak"] + 1) if correct else 0
        interval = _INTERVALS[min(new_streak, len(_INTERVALS) - 1)]
        next_review = (date.today() + timedelta(days=interval)).isoformat()
        total = row["total_attempts"] + 1
        correct_count = row["correct_attempts"] + (1 if correct else 0)

        conn.execute(
            "UPDATE cards SET streak=?, next_review=?, total_attempts=?, correct_attempts=? WHERE id=?",
            (new_streak, next_review, total, correct_count, card_id),
        )
        return {"streak": new_streak, "next_review": next_review}


def get_stats() -> dict:
    today = date.today().isoformat()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    with _connect() as conn:
        total    = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        mastered = conn.execute("SELECT COUNT(*) FROM cards WHERE streak >= 5").fetchone()[0]
        learning = conn.execute("SELECT COUNT(*) FROM cards WHERE streak BETWEEN 1 AND 4").fetchone()[0]
        new      = conn.execute("SELECT COUNT(*) FROM cards WHERE total_attempts = 0").fetchone()[0]
        due      = conn.execute("SELECT COUNT(*) FROM cards WHERE next_review <= ?", (today,)).fetchone()[0]
        added_this_week = conn.execute(
            "SELECT COUNT(*) FROM cards WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]

        acc = conn.execute(
            "SELECT SUM(correct_attempts), SUM(total_attempts) FROM cards WHERE total_attempts > 0"
        ).fetchone()
        accuracy = round(acc[0] / acc[1] * 100) if acc[1] else None

        hardest = conn.execute(
            "SELECT word, translation FROM cards WHERE total_attempts > 0 "
            "ORDER BY CAST(correct_attempts AS REAL) / total_attempts ASC LIMIT 1"
        ).fetchone()

        return {
            "total": total,
            "mastered": mastered,
            "learning": learning,
            "new": new,
            "due_today": due,
            "added_this_week": added_this_week,
            "accuracy_pct": accuracy,
            "hardest_word": dict(hardest) if hardest else None,
        }
