import json

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import POLICY_SYSTEM_PROMPT, POLICY_USER_TEMPLATE
from llm.schemas import PolicyResponse
from state import PolicyDecision, TutorState, PipelineError


def _fallback_decision_for_segment(seg, reason: str) -> PolicyDecision:
    if getattr(seg, "is_fallback", False):
        return PolicyDecision(
            segment_id=seg.segment_id,
            decision="clarify",
            reason=(
                "This segment was created by a fallback interpreter because the original "
                "request could not be safely classified. Ask the user to rephrase it as "
                "a neutral academic tutoring question."
            ),
            intent_type="ambiguous",
            can_be_handled_as_tutoring_task=False,
            handled_domain=None,
            transformed_task_text=None,
            abstracted_task_text=None,
            explain_handling=True,
        )

    return PolicyDecision(
        segment_id=seg.segment_id,
        decision="clarify",
        reason=(
            f"The policy module could not classify this segment because of {reason}. "
            "Ask the user to rephrase the tutoring request."
        ),
        intent_type="ambiguous",
        can_be_handled_as_tutoring_task=False,
        handled_domain=None,
        transformed_task_text=None,
        abstracted_task_text=None,
        explain_handling=True,
    )


def _apply_policy_fallback(state: TutorState, reason: str, message: str) -> TutorState:
    state.errors.append(
        PipelineError(
            module="policy",
            error_type=reason,
            message=message,
            recoverable=True,
        )
    )

    state.decisions = [
        _fallback_decision_for_segment(seg, reason)
        for seg in state.segments
    ]

    return state


def run(state: TutorState) -> TutorState:
    if any(getattr(seg, "is_fallback", False) for seg in state.segments):
        state.decisions = [
            _fallback_decision_for_segment(seg, seg.fallback_reason or "interpret_fallback")
            for seg in state.segments
        ]
        return state

    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    segments_json = json.dumps(
        [s.model_dump() for s in state.segments],
        ensure_ascii=False,
        indent=2,
    )

    context_resolution_json = (
        state.context_resolution.model_dump_json(indent=2)
        if state.context_resolution
        else "{}"
    )

    conversation_context_json = (
        state.conversation_context.model_dump_json(indent=2)
        if state.conversation_context
        else "{}"
    )

    try:
        result = client.call_json(
            system_prompt=POLICY_SYSTEM_PROMPT,
            user_prompt=POLICY_USER_TEMPLATE.format(
                raw_input=state.raw_input,
                resolved_input=state.resolved_input or state.raw_input,
                context_resolution_json=context_resolution_json,
                conversation_context_json=conversation_context_json,
                structure_type=state.structure_type,
                segments_json=segments_json,
            ),
            response_model=PolicyResponse,
        )

    except LLMContentFilterError:
        return _apply_policy_fallback(
            state,
            reason="provider_content_filter",
            message="The policy model call was blocked by the provider content filter.",
        )

    except LLMJSONParseError:
        return _apply_policy_fallback(
            state,
            reason="policy_json_parse_error",
            message="The policy model returned output that could not be parsed into the expected schema.",
        )

    except LLMProviderError:
        return _apply_policy_fallback(
            state,
            reason="llm_provider_error",
            message="The policy model call failed due to a provider/API error.",
        )

    except Exception as e:
        return _apply_policy_fallback(
            state,
            reason="unexpected_error",
            message=f"The policy module failed unexpectedly: {type(e).__name__}: {e}",
        )

    cleaned = []
    for d in result.decisions:
        data = d.model_dump()
        if data.get("reason") is None:
            data["reason"] = ""
        cleaned.append(PolicyDecision.model_validate(data))

    state.decisions = cleaned
    return state