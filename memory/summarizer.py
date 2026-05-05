from __future__ import annotations

from typing import Any
from uuid import uuid4

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import (
    MEMORY_SUMMARIZER_SYSTEM_PROMPT,
    MEMORY_SUMMARIZER_USER_TEMPLATE,
)
from llm.schemas import MemoryRecordResponse


def _normalize_text(text: str | None) -> str:
    return " ".join((text or "").strip().split())


def _shorten(text: str | None, max_chars: int = 1200) -> str:
    text = _normalize_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _fallback_memory_record(
    *,
    domain: str,
    task_id: str,
    segment_id: str,
    task_text: str,
    answer_text: str,
    solver_note: str,
    reason: str,
) -> dict:
    """
    Deterministic fallback if the memory summarizer fails.

    This still avoids using the beginning of task_text as the only topic.
    """
    return {
        "record_id": str(uuid4()),
        "task_id": task_id,
        "segment_id": segment_id,
        "domain": domain,
        "topic_title": f"{domain.title()} tutoring topic",
        "learning_summary": (
            f"The user asked a {domain} tutoring question, and the tutor provided "
            f"a valid answer. Summary fallback reason: {reason}."
        ),
        "key_concepts": [],
        "source_task_text": _shorten(task_text, max_chars=1200),
        "source_answer_text": _shorten(answer_text, max_chars=1800),
        "solver_note": solver_note,
        "memory_status": "fallback_summary",
    }


def summarize_answer_for_memory(
    *,
    state: Any,
    task: Any,
    answer: Any,
) -> dict:
    """
    Convert a valid task-answer pair into a semantic memory record.
    """
    domain = getattr(task, "task_type", "") or getattr(answer, "task_type", "")
    task_id = getattr(task, "task_id", "") or getattr(answer, "task_id", "")
    segment_id = getattr(task, "segment_id", "") or getattr(answer, "segment_id", "")

    task_text = _normalize_text(getattr(task, "task_text", ""))
    answer_text = _normalize_text(getattr(answer, "answer_text", ""))
    solver_note = _normalize_text(getattr(answer, "solver_notes", ""))

    if not domain or not task_text or not answer_text:
        return _fallback_memory_record(
            domain=domain or "unknown",
            task_id=task_id,
            segment_id=segment_id,
            task_text=task_text,
            answer_text=answer_text,
            solver_note=solver_note,
            reason="missing_required_fields",
        )

    try:
        client = LLMClient(
            model=state.config["model"],
            api_key=state.config.get("api_key"),
            endpoint=state.config.get("endpoint"),
            api_version=state.config.get("api_version"),
        )

        result = client.call_json(
            system_prompt=MEMORY_SUMMARIZER_SYSTEM_PROMPT,
            user_prompt=MEMORY_SUMMARIZER_USER_TEMPLATE.format(
                domain=domain,
                task_text=_shorten(task_text, max_chars=1200),
                answer_text=_shorten(answer_text, max_chars=1800),
                solver_note=solver_note,
            ),
            response_model=MemoryRecordResponse,
        )

        return {
            "record_id": str(uuid4()),
            "task_id": task_id,
            "segment_id": segment_id,
            "domain": domain,
            "topic_title": _shorten(result.topic_title, max_chars=120),
            "learning_summary": _shorten(result.learning_summary, max_chars=500),
            "key_concepts": [
                _shorten(item, max_chars=80)
                for item in result.key_concepts[:5]
                if isinstance(item, str) and item.strip()
            ],
            "source_task_text": _shorten(task_text, max_chars=1200),
            "source_answer_text": _shorten(answer_text, max_chars=1800),
            "solver_note": solver_note,
            "memory_status": "semantic_summary",
        }

    except (LLMContentFilterError, LLMJSONParseError, LLMProviderError) as e:
        return _fallback_memory_record(
            domain=domain,
            task_id=task_id,
            segment_id=segment_id,
            task_text=task_text,
            answer_text=answer_text,
            solver_note=solver_note,
            reason=type(e).__name__,
        )

    except Exception as e:
        return _fallback_memory_record(
            domain=domain,
            task_id=task_id,
            segment_id=segment_id,
            task_text=task_text,
            answer_text=answer_text,
            solver_note=solver_note,
            reason=f"unexpected:{type(e).__name__}",
        )