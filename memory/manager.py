from copy import deepcopy
from typing import Any

from memory.summarizer import summarize_answer_for_memory

SUPPORTED_TUTORING_DOMAINS = {"math", "history", "summary"}

# Summary requests are supported, but they are not substantive taught topics.
TAUGHT_TOPIC_DOMAINS = {"math", "history"}

RECENT_TURN_LIMIT = 15
LEARNING_RECORD_LIMIT = 15

SUCCESS_SOLVER_NOTES = {
    "ok",
    "ok_transformed_task",
    "answered_with_reliable_framing",
    "answered_without_unverified_support",
    "summary_from_selected_memory",
}

NON_MEMORY_SOLVER_NOTES = {
    "summary_no_usable_memory",
    "summary_no_successful_tutoring_content",
    "summary_memory_missing_or_malformed",
}


def init_memory() -> dict:
    return {
        "recent_turns": [],
        "learning_records": [],
        "session_summary": {
            "brief": "",
            "main_topics": [],
            "recent_focus": "",
            "user_difficulties": [],
            "updated_turn_count": 0,
        },
        "active_thread": _default_active_thread(),
        "user_profile": {},
    }


def _normalize_text(text: str | None) -> str:
    return " ".join((text or "").strip().split())


def _shorten(text: str | None, max_chars: int = 120) -> str:
    """
    Compact display helper.

    Use this for UI/debug/session_summary.brief only.
    Do not use it as the only stored representation of a task.
    """
    text = _normalize_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _solver_note(answer: Any) -> str:
    note = getattr(answer, "solver_notes", None)
    if not isinstance(note, str):
        return ""
    return note.strip()


def _make_turn_id(updated: dict) -> str:
    return f"turn_{len(updated.get('recent_turns', [])) + 1}"


def _first_task_domain(state: Any) -> str:
    domains = _task_domains_from_state(state)
    for domain in domains:
        if domain in {"math", "history"}:
            return domain
    return domains[0] if domains else ""


def _first_task_text(state: Any) -> str:
    for task in getattr(state, "tasks", []):
        text = getattr(task, "task_text", "")
        if text:
            return text
    return getattr(state, "resolved_input", None) or getattr(state, "raw_input", "")


def _first_answer_text(state: Any) -> str:
    for answer in getattr(state, "answers", []):
        if _answer_record_is_valid_for_memory(answer):
            return getattr(answer, "answer_text", "")
    return ""


def _extract_answer_outline_for_thread(state: Any) -> list[str]:
    answer_text = _first_answer_text(state)
    if not answer_text:
        return []

    lines = []
    for raw_line in answer_text.splitlines():
        line = _normalize_text(raw_line)
        if not line:
            continue

        cleaned = line.lstrip("-*0123456789.）) ").strip()
        if len(cleaned) < 8:
            continue

        lines.append(_shorten(cleaned, max_chars=140))

        if len(lines) >= 5:
            break

    if lines:
        return lines

    return [_shorten(answer_text, max_chars=180)]


def _extract_latest_answer_summary(state: Any) -> str:
    answer_text = _first_answer_text(state)
    if not answer_text:
        return ""
    return _shorten(answer_text, max_chars=260)


def _should_update_active_thread(state: Any) -> bool:
    if _state_is_summary_only_turn(state):
        return False

    if not _state_has_valid_answer(state):
        return False

    domain = _first_task_domain(state)
    return domain in {"math", "history"}


def _guess_topic_title(state: Any) -> str:
    for record in getattr(state, "memory_records_for_current_turn", []):
        if isinstance(record, dict) and record.get("topic_title"):
            return record["topic_title"]

    for answer in getattr(state, "answers", []):
        if getattr(answer, "task_type", "") in {"math", "history"}:
            return _shorten(_first_task_text(state), max_chars=100)

    return _shorten(_first_task_text(state), max_chars=100)


def _should_start_new_thread(state: Any, previous_thread: dict) -> bool:
    if not previous_thread or previous_thread.get("status") in {"", "empty", "closed"}:
        return True

    relation = "standalone"
    if getattr(state, "context_resolution", None):
        relation = state.context_resolution.relation_to_previous

    if relation in {"follow_up", "continuation", "correction", "clarification"}:
        return False

    new_domain = _first_task_domain(state)
    old_domain = previous_thread.get("domain", "")

    if new_domain and old_domain and new_domain != old_domain:
        return True

    if relation in {"standalone", "unrelated_new_topic"}:
        return True

    return False


def _update_active_thread(updated: dict, state: Any) -> None:
    if not _should_update_active_thread(state):
        return

    previous = updated.get("active_thread", _default_active_thread())
    if not isinstance(previous, dict):
        previous = _default_active_thread()

    current_turn = updated["recent_turns"][-1] if updated.get("recent_turns") else {}
    turn_id = current_turn.get("turn_id", "")

    start_new = _should_start_new_thread(state, previous)

    if start_new:
        thread_id = f"thread_{turn_id}" if turn_id else f"thread_{len(updated.get('recent_turns', []))}"
        turn_ids = [turn_id] if turn_id else []
    else:
        thread_id = previous.get("thread_id", "") or f"thread_{turn_id}"
        turn_ids = list(previous.get("turn_ids", []) or [])
        if turn_id and turn_id not in turn_ids:
            turn_ids.append(turn_id)

    updated["active_thread"] = {
        "thread_id": thread_id,
        "domain": _first_task_domain(state),
        "topic_title": _guess_topic_title(state),
        "latest_user_goal": _shorten(
            getattr(state, "resolved_input", None) or getattr(state, "raw_input", ""),
            max_chars=220,
        ),
        "latest_answer_summary": _extract_latest_answer_summary(state),
        "last_answer_outline": _extract_answer_outline_for_thread(state),
        "open_questions": [],
        "last_successful_turn_id": turn_id,
        "turn_ids": turn_ids[-10:],
        "status": "active",
    }

    if turn_id:
        current_turn["thread_id"] = thread_id


def _get_turns_for_active_thread(memory: dict) -> list[dict]:
    active_thread = memory.get("active_thread", {})
    if not isinstance(active_thread, dict):
        return []

    thread_id = active_thread.get("thread_id", "")
    turn_ids = set(active_thread.get("turn_ids", []) or [])

    turns = []
    for turn in memory.get("recent_turns", []):
        if not isinstance(turn, dict):
            continue

        if turn_ids and turn.get("turn_id") in turn_ids:
            turns.append(turn)
        elif thread_id and turn.get("thread_id") == thread_id:
            turns.append(turn)

    return turns


def _answer_record_is_valid_for_memory(answer: Any) -> bool:
    """
    Decide whether an answer counts as successful memory.

    This function intentionally avoids keyword matching over answer_text.
    It uses structured solver_notes produced by the solver modules/prompts.
    """
    if answer is None:
        return False

    answer_text = getattr(answer, "answer_text", None)
    if not isinstance(answer_text, str) or not answer_text.strip():
        return False

    note = _solver_note(answer)

    if note.startswith("solver_failed:"):
        return False

    if note in NON_MEMORY_SOLVER_NOTES:
        return False

    if note in SUCCESS_SOLVER_NOTES:
        return True

    # Backward-compatible default:
    # If an older solver did not set solver_notes but produced an answer,
    # treat it as usable unless structured failure metadata says otherwise.
    return note == ""


def _state_has_valid_answer(state: Any) -> bool:
    for answer in getattr(state, "answers", []):
        if _answer_record_is_valid_for_memory(answer):
            return True
    return False


def _task_domains_from_state(state: Any) -> list[str]:
    domains = []

    for task in getattr(state, "tasks", []):
        task_type = getattr(task, "task_type", None)
        if task_type:
            domains.append(task_type)

    return domains


def _state_is_summary_only_turn(state: Any) -> bool:
    """
    True when this turn only asked for conversation summary.

    Summary-only turns are visible history, but should not become content
    for future conversation summaries.
    """
    domains = _task_domains_from_state(state)
    return bool(domains) and all(domain == "summary" for domain in domains)


def _state_has_errors_without_valid_answer(state: Any) -> bool:
    return bool(getattr(state, "errors", [])) and not _state_has_valid_answer(state)


def _state_all_decisions_non_answered(state: Any) -> bool:
    """
    True when the pipeline made decisions, but none led to a handled answer.

    This is structured-state based. It avoids scanning final_response text.
    """
    decisions = getattr(state, "decisions", [])
    if not decisions:
        return False

    answerable = [
        d for d in decisions
        if getattr(d, "decision", None) in {"accept", "transform", "abstract"}
        and getattr(d, "can_be_handled_as_tutoring_task", False)
    ]

    return not answerable


def _classify_turn_for_memory(state: Any) -> str:
    """
    Classify the current turn using structured pipeline state.

    Values:
    - answered: at least one structurally valid answer exists
    - error: no valid answer and pipeline errors occurred
    - not_answered: request was handled as reject/clarify/non-answer
    - other: no solver answer, but no clear failure either
    """
    if _state_has_valid_answer(state):
        return "answered"

    if _state_has_errors_without_valid_answer(state):
        return "error"

    if _state_all_decisions_non_answered(state):
        return "not_answered"

    return "other"


def _get_task_by_task_id(state: Any) -> dict:
    return {
        task.task_id: task
        for task in getattr(state, "tasks", [])
    }


def _memory_record_key(record: dict) -> tuple:
    concepts = tuple(sorted(record.get("key_concepts", [])))
    return (
        record.get("domain"),
        record.get("topic_title"),
        concepts,
    )


def _extract_learning_records_from_state(state: Any) -> list[dict]:
    tasks_by_id = _get_task_by_task_id(state)
    records = []

    for answer in getattr(state, "answers", []):
        if not _answer_record_is_valid_for_memory(answer):
            continue

        if getattr(answer, "task_type", None) not in TAUGHT_TOPIC_DOMAINS:
            continue

        task = tasks_by_id.get(answer.task_id)
        if task is None:
            continue

        record = summarize_answer_for_memory(
            state=state,
            task=task,
            answer=answer,
        )

        records.append(record)

    return records


def _append_learning_records(updated: dict, state: Any) -> None:
    new_records = _extract_learning_records_from_state(state)

    existing_keys = {
        _memory_record_key(item)
        for item in updated.get("learning_records", [])
        if isinstance(item, dict)
    }

    for record in new_records:
        key = _memory_record_key(record)

        if key in existing_keys:
            continue

        updated["learning_records"].append(record)
        existing_keys.add(key)

    updated["learning_records"] = updated["learning_records"][-LEARNING_RECORD_LIMIT:]


def _get_decision_by_segment_id(state: Any) -> dict:
    return {
        decision.segment_id: decision
        for decision in getattr(state, "decisions", [])
    }


def _get_answer_by_task_id(state: Any) -> dict:
    return {
        answer.task_id: answer
        for answer in getattr(state, "answers", [])
    }


def _append_recent_turn(updated: dict, state: Any) -> None:
    turn_status = _classify_turn_for_memory(state)
    task_domains = _task_domains_from_state(state)
    is_summary_only = _state_is_summary_only_turn(state)

    context_resolution = getattr(state, "context_resolution", None)

    relation_to_previous = "standalone"
    context_used = False
    referenced_turn_ids = []
    summary_scope = None

    if context_resolution is not None:
        relation_to_previous = getattr(context_resolution, "relation_to_previous", "standalone")
        context_used = bool(getattr(context_resolution, "needs_previous_context", False))
        referenced_turn_ids = getattr(context_resolution, "referenced_turn_ids", []) or []
        summary_scope = getattr(context_resolution, "summary_scope", None)

    updated["recent_turns"].append(
        {
            "turn_id": _make_turn_id(updated),
            "thread_id": "",
            "user": getattr(state, "raw_input", ""),
            "assistant": getattr(state, "final_response", ""),
            "resolved_input": getattr(state, "resolved_input", None) or getattr(state, "raw_input", ""),
            "relation_to_previous": relation_to_previous,
            "context_used": context_used,
            "referenced_turn_ids": referenced_turn_ids,
            "summary_scope": summary_scope,
            "status": turn_status,
            "task_domains": task_domains,
            "summary_only": is_summary_only,
            "summary_eligible": (
                turn_status in {"answered", "other"}
                and not is_summary_only
            ),
        }
    )

    updated["recent_turns"] = updated["recent_turns"][-RECENT_TURN_LIMIT:]


def _refresh_session_summary(updated: dict) -> None:
    learning_records = [
        item for item in updated.get("learning_records", [])
        if isinstance(item, dict)
    ]

    active_thread = updated.get("active_thread", {})
    if not isinstance(active_thread, dict):
        active_thread = _default_active_thread()

    main_topics = []
    for item in learning_records[-10:]:
        topic = item.get("topic_title", "")
        if topic and topic not in main_topics:
            main_topics.append(topic)

    recent_focus = active_thread.get("topic_title", "") or ""

    brief_parts = []

    if main_topics:
        brief_parts.append("Main tutoring topics: " + "; ".join(main_topics[-6:]))

    if recent_focus:
        brief_parts.append(f"Current thread: {recent_focus}")

    if active_thread.get("latest_answer_summary"):
        brief_parts.append(
            "Latest answer: " + _shorten(active_thread.get("latest_answer_summary", ""), max_chars=220)
        )

    if not brief_parts:
        eligible_turns = [
            item for item in updated.get("recent_turns", [])
            if isinstance(item, dict)
            and item.get("summary_eligible", True)
            and not item.get("summary_only", False)
            and item.get("status") in {"answered", "other"}
        ]

        if eligible_turns:
            turn_texts = [
                _shorten(item.get("user", ""), max_chars=160)
                for item in eligible_turns[-5:]
                if item.get("user")
            ]
            if turn_texts:
                brief_parts.append("Recent conversation topics: " + "; ".join(turn_texts))

    updated["session_summary"] = {
        "brief": " ".join(brief_parts),
        "main_topics": main_topics[-10:],
        "recent_focus": recent_focus,
        "user_difficulties": updated.get("session_summary", {}).get("user_difficulties", []),
        "updated_turn_count": len(updated.get("recent_turns", [])),
    }


def _default_active_thread() -> dict:
    return {
        "thread_id": "",
        "domain": "",
        "topic_title": "",
        "latest_user_goal": "",
        "latest_answer_summary": "",
        "last_answer_outline": [],
        "open_questions": [],
        "last_successful_turn_id": "",
        "turn_ids": [],
        "status": "empty",
    }



def load_memory(memory: dict | None) -> dict:
    if memory is None:
        return init_memory()

    loaded = deepcopy(memory)

    loaded.setdefault("recent_turns", [])
    loaded.setdefault("learning_records", [])
    loaded.setdefault("session_summary", {})
    loaded.setdefault("active_thread", _default_active_thread())
    loaded.setdefault("user_profile", {})

    if not isinstance(loaded["recent_turns"], list):
        loaded["recent_turns"] = []

    if not isinstance(loaded["learning_records"], list):
        loaded["learning_records"] = []

    if not isinstance(loaded["session_summary"], dict):
        loaded["session_summary"] = {}

    if not isinstance(loaded["active_thread"], dict):
        loaded["active_thread"] = _default_active_thread()

    if not isinstance(loaded["user_profile"], dict):
        loaded["user_profile"] = {}

    loaded["session_summary"].setdefault("brief", "")
    loaded["session_summary"].setdefault("main_topics", [])
    loaded["session_summary"].setdefault("recent_focus", "")
    loaded["session_summary"].setdefault("user_difficulties", [])
    loaded["session_summary"].setdefault("updated_turn_count", 0)

    default_thread = _default_active_thread()
    for key, value in default_thread.items():
        loaded["active_thread"].setdefault(key, value)

    for idx, turn in enumerate(loaded["recent_turns"]):
        if not isinstance(turn, dict):
            continue

        turn.setdefault("turn_id", f"turn_{idx + 1}")
        turn.setdefault("thread_id", "")
        turn.setdefault("resolved_input", turn.get("user", ""))
        turn.setdefault("relation_to_previous", "standalone")
        turn.setdefault("context_used", False)
        turn.setdefault("referenced_turn_ids", [])
        turn.setdefault("summary_scope", None)
        turn.setdefault("status", "other")
        turn.setdefault("task_domains", [])
        turn.setdefault("summary_only", False)
        turn.setdefault(
            "summary_eligible",
            turn.get("status") in {"answered", "other"}
            and not turn.get("summary_only", False),
        )

    cleaned_records = []
    for item in loaded.get("learning_records", []):
        if not isinstance(item, dict):
            continue

        item.setdefault("record_id", "")
        item.setdefault("task_id", "")
        item.setdefault("segment_id", "")
        item.setdefault("domain", "unknown")
        item.setdefault("topic_title", "")
        item.setdefault("learning_summary", "")
        item.setdefault("key_concepts", [])
        item.setdefault("source_task_text", "")
        item.setdefault("source_answer_text", "")
        item.setdefault("solver_note", "")
        item.setdefault("memory_status", "unknown")

        if not isinstance(item["key_concepts"], list):
            item["key_concepts"] = []

        cleaned_records.append(item)

    loaded["learning_records"] = cleaned_records

    return loaded
    

def update_memory(memory: dict, state: Any) -> dict:
    updated = load_memory(memory)

    _append_recent_turn(updated, state)
    _append_learning_records(updated, state)
    _update_active_thread(updated, state)
    _refresh_session_summary(updated)

    return updated


def memory_debug_view(memory: dict | None) -> dict:
    loaded = load_memory(memory)

    return {
        "recent_turns_count": len(loaded.get("recent_turns", [])),
        "learning_records_count": len(loaded.get("learning_records", [])),

        "session_summary": loaded.get("session_summary", {}),
        "active_thread": loaded.get("active_thread", {}),

        "learning_records_preview": [
            {
                "domain": item.get("domain"),
                "topic_title": item.get("topic_title"),
                "learning_summary": _shorten(
                    item.get("learning_summary", ""),
                    max_chars=220,
                ),
                "key_concepts": item.get("key_concepts", []),
                "memory_status": item.get("memory_status"),
            }
            for item in loaded.get("learning_records", [])
            if isinstance(item, dict)
        ],

        "recent_turn_statuses": [
            {
                "turn_id": turn.get("turn_id"),
                "thread_id": turn.get("thread_id"),
                "status": turn.get("status"),
                "task_domains": turn.get("task_domains"),
                "relation_to_previous": turn.get("relation_to_previous"),
                "context_used": turn.get("context_used"),
                "summary_scope": turn.get("summary_scope"),
                "summary_only": turn.get("summary_only"),
                "summary_eligible": turn.get("summary_eligible"),
                "user": _shorten(turn.get("user", ""), max_chars=100),
                "resolved_input": _shorten(turn.get("resolved_input", ""), max_chars=100),
            }
            for turn in loaded.get("recent_turns", [])
            if isinstance(turn, dict)
        ],
    }