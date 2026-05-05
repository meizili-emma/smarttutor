import re
from state import ConversationContext, TutorState


def _normalize_text(text: str | None) -> str:
    return " ".join((text or "").strip().split())


def _select_recent_turns(memory: dict, limit: int = 8) -> list[dict]:
    turns = memory.get("recent_turns", [])
    if not isinstance(turns, list):
        return []

    usable = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue

        usable.append(
            {
                "turn_id": turn.get("turn_id", ""),
                "thread_id": turn.get("thread_id", ""),
                "user": _normalize_text(turn.get("user", ""))[:700],
                "assistant": _normalize_text(turn.get("assistant", ""))[:1000],
                "status": turn.get("status", ""),
                "task_domains": turn.get("task_domains", []),
                "summary_only": turn.get("summary_only", False),
                "summary_eligible": turn.get("summary_eligible", True),
                "relation_to_previous": turn.get("relation_to_previous", "standalone"),
                "resolved_input": _normalize_text(turn.get("resolved_input", ""))[:700],
            }
        )

    return usable[-limit:]


def _select_active_thread(memory: dict) -> dict:
    thread = memory.get("active_thread", {})
    if not isinstance(thread, dict):
        return {}

    return {
        "thread_id": thread.get("thread_id", ""),
        "domain": thread.get("domain", ""),
        "topic_title": thread.get("topic_title", ""),
        "latest_user_goal": thread.get("latest_user_goal", ""),
        "latest_answer_summary": thread.get("latest_answer_summary", ""),
        "last_answer_outline": thread.get("last_answer_outline", []),
        "open_questions": thread.get("open_questions", []),
        "last_successful_turn_id": thread.get("last_successful_turn_id", ""),
        "turn_ids": thread.get("turn_ids", []),
        "status": thread.get("status", ""),
    }


def _select_relevant_learning_records(memory: dict, raw_input: str, limit: int = 8) -> list[dict]:
    records = memory.get("learning_records", [])
    if not isinstance(records, list):
        return []

    raw = _normalize_text(raw_input).lower()
    raw_tokens = set(re.findall(r"[a-zA-Z0-9_]+", raw))

    scored = []
    for record in records:
        if not isinstance(record, dict):
            continue

        blob = " ".join(
            [
                str(record.get("domain", "")),
                str(record.get("topic_title", "")),
                str(record.get("learning_summary", "")),
                " ".join(record.get("key_concepts", []) or []),
            ]
        ).lower()

        record_tokens = set(re.findall(r"[a-zA-Z0-9_]+", blob))
        score = len(raw_tokens & record_tokens)

        scored.append(
            (
                score,
                {
                    "record_id": record.get("record_id", ""),
                    "domain": record.get("domain", ""),
                    "topic_title": record.get("topic_title", ""),
                    "learning_summary": record.get("learning_summary", ""),
                    "key_concepts": record.get("key_concepts", []),
                    "memory_status": record.get("memory_status", ""),
                },
            )
        )

    scored.sort(key=lambda x: x[0])
    selected = [item for score, item in scored if score > 0]

    if not selected:
        selected = [item for _, item in scored[-limit:]]

    return selected[-limit:]


def _build_conversation_context(memory: dict, raw_input: str) -> ConversationContext:
    session_summary = memory.get("session_summary", {})
    if not isinstance(session_summary, dict):
        session_summary = {}

    return ConversationContext(
        recent_turns=_select_recent_turns(memory, limit=5),
        active_thread=_select_active_thread(memory),
        session_summary=session_summary,
        relevant_learning_records=_select_relevant_learning_records(
            memory,
            raw_input,
            limit=5,
        ),
    )


def run(state: TutorState) -> TutorState:
    state.conversation_context = _build_conversation_context(
        state.memory or {},
        state.raw_input,
    )
    return state