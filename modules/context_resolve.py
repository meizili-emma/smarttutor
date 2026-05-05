import json

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import CONTEXT_RESOLVE_SYSTEM_PROMPT, CONTEXT_RESOLVE_USER_TEMPLATE
from llm.schemas import ContextResolutionResponse
from state import ContextResolution, PipelineError, TutorState


SUMMARY_KEYWORDS = {
    "summarize",
    "summary",
    "recap",
    "covered",
    "discussed",
    "conversation so far",
    "what have we",
    "what did we",
}

FOLLOW_UP_KEYWORDS = {
    "why",
    "how",
    "continue",
    "explain more",
    "more detail",
    "make it simpler",
    "simpler",
    "shorter",
    "concise",
    "the second",
    "second one",
    "that",
    "this",
    "it",
}


def _lower(text: str | None) -> str:
    return (text or "").strip().lower()


def _is_explicit_summary_request(raw_input: str) -> bool:
    text = _lower(raw_input)
    return any(k in text for k in SUMMARY_KEYWORDS)


def _infer_summary_scope(raw_input: str) -> tuple[str, str | None]:
    text = _lower(raw_input)

    domain_filter = None
    if "math" in text:
        domain_filter = "math"
    elif "history" in text:
        domain_filter = "history"

    if domain_filter:
        return "domain_filtered", domain_filter

    if "last question" in text or "last answer" in text or "previous answer" in text:
        return "latest_turn", None

    if "latest conversation" in text or "current conversation" in text or "current thread" in text or "latest thread" in text:
        return "active_thread", None

    if "so far" in text or "whole" in text or "everything" in text:
        return "whole_session", None

    if "recent" in text:
        return "recent_session", None

    return "active_thread", None


def _looks_like_follow_up(raw_input: str) -> bool:
    text = _lower(raw_input)
    if len(text.split()) <= 4 and any(k == text or text.startswith(k) for k in FOLLOW_UP_KEYWORDS):
        return True
    return any(k in text for k in FOLLOW_UP_KEYWORDS)


def _has_previous_context(state: TutorState) -> bool:
    ctx = state.conversation_context
    if not ctx:
        return False
    return bool(ctx.recent_turns or ctx.active_thread or ctx.relevant_learning_records)


def _context_to_json(state: TutorState) -> str:
    ctx = state.conversation_context
    if not ctx:
        return "{}"
    return json.dumps(ctx.model_dump(), ensure_ascii=False, indent=2)


def _deterministic_context_resolution(state: TutorState, reason: str) -> ContextResolution:
    raw = state.raw_input

    if _is_explicit_summary_request(raw):
        scope, domain_filter = _infer_summary_scope(raw)
        return ContextResolution(
            relation_to_previous="summary_request",
            needs_previous_context=True,
            referenced_turn_ids=[],
            referenced_topic=None,
            resolved_input=f"Summarize the previous conversation using available memory. Scope: {scope}.",
            resolution_confidence="medium",
            reason=reason or "The input explicitly asks for a conversation summary.",
            summary_scope=scope,
            summary_domain_filter=domain_filter,
        )

    if _looks_like_follow_up(raw) and _has_previous_context(state):
        return ContextResolution(
            relation_to_previous="follow_up",
            needs_previous_context=True,
            referenced_turn_ids=[],
            referenced_topic=None,
            resolved_input=raw,
            resolution_confidence="low",
            reason=(
                reason
                or "The input appears to refer to previous context, but automatic context resolution was unavailable."
            ),
            summary_scope=None,
            summary_domain_filter=None,
        )

    return ContextResolution(
        relation_to_previous="standalone",
        needs_previous_context=False,
        referenced_turn_ids=[],
        referenced_topic=None,
        resolved_input=raw,
        resolution_confidence="medium",
        reason=reason or "The input can be treated as a standalone task.",
        summary_scope=None,
        summary_domain_filter=None,
    )


def _call_context_resolver(state: TutorState) -> ContextResolutionResponse:
    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    return client.call_json(
        system_prompt=CONTEXT_RESOLVE_SYSTEM_PROMPT,
        user_prompt=CONTEXT_RESOLVE_USER_TEMPLATE.format(
            raw_input=state.raw_input,
            conversation_context_json=_context_to_json(state),
        ),
        response_model=ContextResolutionResponse,
    )


def run(state: TutorState) -> TutorState:
    if not state.conversation_context:
        state.context_resolution = _deterministic_context_resolution(
            state,
            reason="No selected conversation context was available.",
        )
        state.resolved_input = state.context_resolution.resolved_input
        return state

    # Deterministic fast path for explicit summary requests.
    # This makes "summarize latest conversation" reliable even if the resolver LLM fails.
    if _is_explicit_summary_request(state.raw_input):
        state.context_resolution = _deterministic_context_resolution(
            state,
            reason="The input explicitly asks for a user-facing conversation summary.",
        )
        state.resolved_input = state.context_resolution.resolved_input
        return state

    try:
        result = _call_context_resolver(state)
        state.context_resolution = ContextResolution.model_validate(result.model_dump())
        state.resolved_input = state.context_resolution.resolved_input or state.raw_input
        return state

    except LLMContentFilterError:
        error_type = "provider_content_filter"
        message = "The context resolver model call was blocked by the provider content filter."

    except LLMJSONParseError:
        error_type = "context_resolver_json_parse_error"
        message = "The context resolver returned output that could not be parsed."

    except LLMProviderError:
        error_type = "llm_provider_error"
        message = "The context resolver model call failed due to a provider/API error."

    except Exception as e:
        error_type = "unexpected_error"
        message = f"The context resolver failed unexpectedly: {type(e).__name__}: {e}"

    state.errors.append(
        PipelineError(
            module="context_resolve",
            error_type=error_type,
            message=message,
            recoverable=True,
        )
    )

    state.context_resolution = _deterministic_context_resolution(
        state,
        reason=message,
    )
    state.resolved_input = state.context_resolution.resolved_input
    return state