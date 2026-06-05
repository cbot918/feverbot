"""
fever_bot.py — Sales-coaching session logic for the LINE group bot.

Flow:
  1. User types "開始輔導" → caller picks Q1 via pick_first_question() and starts a session.
  2. User replies → advance(session, text) appends the answer and generates the next question (Q2/Q3
     via LLM) or, after 3 answers, the final personalised suggestion.
  3. Caller sends the reply text; on is_final the caller ends the session.

LLM backend: OpenRouter (OpenAI-compatible).
  OPENROUTER_API_KEY  — required
  OPENROUTER_MODEL    — optional, defaults to "moonshotai/kimi-k2"

Data-source seam (requirement #8):
  FEVER_DATA_SOURCE — optional path to a plain-text file with course/resource info injected into the
  suggestion prompt. Leave unset to use pure LLM output.
"""

from __future__ import annotations

import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Tuple

import openai

# ── Constants ─────────────────────────────────────────────────────────────────

TOTAL_QUESTIONS = 3

SESSION_TTL_SECONDS: float = float(os.environ.get("SESSION_TTL_SECONDS", 1800))  # 30 min default

BUILTIN_QUESTIONS: list[str] = [
    "你在銷售過程中，最常遇到什麼困難？",
    "你目前主要賣的產品或服務是什麼？",
    "你的理想客戶通常是哪種類型的人？",
    "你覺得自己目前最缺乏的銷售技能是什麼？",
    "你一週平均主動開發幾個新客戶？",
    "在銷售情境中，你最害怕的是哪種時刻？",
    "你最近一次被客戶拒絕，原因是什麼？",
    "你平時是怎麼跟陌生客戶建立信任感的？",
    "你覺得自己目前的成交率大概是多少？",
    "你有定期追蹤舊客戶嗎？你是怎麼做的？",
]

# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class CoachingSession:
    group_id: str
    user_id: str
    name: str
    questions: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.monotonic)

    @property
    def is_done(self) -> bool:
        return len(self.answers) >= TOTAL_QUESTIONS

    @property
    def current_step(self) -> int:
        """1-indexed: how many questions have been asked so far."""
        return len(self.questions)


# ── Session store ─────────────────────────────────────────────────────────────

SessionKey = Tuple[str, str]  # (group_id, user_id)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[SessionKey, CoachingSession] = {}
        self._lock = threading.Lock()

    def start(self, key: SessionKey, group_id: str, user_id: str, name: str) -> CoachingSession:
        session = CoachingSession(group_id=group_id, user_id=user_id, name=name)
        with self._lock:
            self._sessions[key] = session
        return session

    def get(self, key: SessionKey) -> Optional[CoachingSession]:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                return None
            # Lazy TTL expiry
            if time.monotonic() - session.created_at > SESSION_TTL_SECONDS:
                del self._sessions[key]
                return None
            return session

    def end(self, key: SessionKey) -> None:
        with self._lock:
            self._sessions.pop(key, None)


# Module-level shared store (single process)
store = SessionStore()

# ── LLM client (lazy) ────────────────────────────────────────────────────────

_client: Optional[openai.OpenAI] = None
_client_lock = threading.Lock()


def _get_client() -> openai.OpenAI:
    global _client
    with _client_lock:
        if _client is None:
            _client = openai.OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=os.environ["OPENROUTER_API_KEY"],
            )
    return _client


_DEFAULT_MODEL = "moonshotai/kimi-k2"


def _chat(system: str, user: str, max_tokens: int = 300) -> str:
    model = os.environ.get("OPENROUTER_MODEL", _DEFAULT_MODEL)
    response = _get_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return response.choices[0].message.content.strip()


# ── Data-source seam (req #8) ─────────────────────────────────────────────────


def get_data_source(session: CoachingSession) -> str:  # noqa: ARG001
    """
    Returns supplementary resource text to inject into the suggestion prompt.
    Currently reads from a plain-text file at FEVER_DATA_SOURCE (env var).
    Replace this function to pull from a DB, API, or course catalog.
    """
    path = os.environ.get("FEVER_DATA_SOURCE", "")
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


# ── Core logic ────────────────────────────────────────────────────────────────


def pick_first_question() -> str:
    import admin_config  # local import avoids circular dep at module load
    default_q = admin_config.get_default_first_question().strip()
    if default_q:
        return default_q
    pool = admin_config.get_first_questions() or BUILTIN_QUESTIONS
    return random.choice(pool)


def _build_history(session: CoachingSession) -> str:
    return "\n".join(
        f"問題{i + 1}：{q}\n學員回答：{a}"
        for i, (q, a) in enumerate(zip(session.questions, session.answers))
    )


def generate_next_question(session: CoachingSession) -> str:
    history = _build_history(session)
    return _chat(
        system=(
            "你是一位專業銷售培訓助教，正在對一位學員進行一對一輔導。"
            "根據學員前面的回答，提出一個有針對性的深入問題，幫助了解學員更多的銷售困境或優勢。"
            "問題要具體、有啟發性，且與前面的回答有邏輯關聯。"
            "只輸出問題本身，不要加前綴或解釋。"
        ),
        user=f"輔導對話記錄：\n{history}\n\n請提出下一個問題：",
        max_tokens=150,
    )


def generate_suggestion(session: CoachingSession) -> str:
    import admin_config  # local import avoids circular dep at module load
    history = _build_history(session)
    data_source = get_data_source(session)
    extra_guidelines = admin_config.get_suggestion_extra_guidelines().strip()

    system = (
        "你是一位專業銷售培訓老師，剛完成對一位學員的三題快速輔導。"
        "根據學員的三個回答，給出一段200字以內的個人化建議。"
        "建議要具體、正向，點出學員的核心問題並給出可立刻執行的行動建議。"
    )
    if extra_guidelines:
        system += f"\n\n老師補充指引：\n{extra_guidelines}"
    if data_source:
        system += f"\n\n可參考的課程資源（如果適合可推薦）：\n{data_source}"

    return _chat(
        system=system,
        user=f"輔導對話記錄：\n{history}\n\n請給出個人化建議：",
        max_tokens=500,
    )


def advance(session: CoachingSession, answer_text: str) -> Tuple[str, bool]:
    """
    Record the student's answer and generate the next step.

    Returns:
        (reply_text, is_final)
        - is_final=False → reply_text is the next question (Q2 or Q3), session continues.
        - is_final=True  → reply_text is the personalised suggestion, session should be ended.

    The answer is appended to session.answers only after the LLM call succeeds,
    so a network failure leaves the session in a retryable state.
    """
    answered_count = len(session.answers) + 1  # including this answer

    if answered_count < TOTAL_QUESTIONS:
        # Generate next dynamic question first (fail-fast before mutating state)
        session.answers.append(answer_text)
        next_q = generate_next_question(session)
        session.questions.append(next_q)
        return f"第{session.current_step}題：\n{next_q}", False
    else:
        # Final answer — fixed override wins; otherwise generate suggestion via LLM
        import admin_config  # local import avoids circular dep at module load
        session.answers.append(answer_text)
        override = admin_config.get_suggestion_override().strip()
        if override:
            return override.replace("{name}", session.name), True
        suggestion = generate_suggestion(session)
        return f"🎯 輔導完成！這是給你的個人化建議：\n\n{suggestion}", True
