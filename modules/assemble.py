import json

from llm.client import (
    LLMClient,
    LLMContentFilterError,
    LLMJSONParseError,
    LLMProviderError,
)
from llm.prompts import ASSEMBLE_SYSTEM_PROMPT, ASSEMBLE_USER_TEMPLATE
from llm.schemas import AssembleResponse
from state import TutorState, PipelineError


def _collect_explanations(state: TutorState):
    explanations = []

    for decision in state.decisions:
        if decision.decision in {"transform", "abstract", "reject", "clarify"}:
            explanations.append({
                "segment_id": decision.segment_id,
                "decision": decision.decision,
                "reason": decision.reason,
                "explain": decision.explain_handling,
            })

    return explanations


def _has_error(state: TutorState, error_type: str, module: str | None = None) -> bool:
    for err in state.errors:
        if err.error_type != error_type:
            continue
        if module is not None and err.module != module:
            continue
        return True
    return False


def _deterministic_fallback_response(state: TutorState) -> str:
    if (
        state.context_resolution
        and state.context_resolution.relation_to_previous == "summary_request"
    ):
        return (
            "I do not have enough previous conversation in the requested scope to "
            "summarize yet."
        )

    if _has_error(state, "provider_content_filter", module="interpret"):
        return (
            "I could not process the request in its current wording because it was "
            "blocked before the tutoring system could classify it. Please rephrase it "
            "as a neutral academic tutoring question. I can help with math tutoring, "
            "history tutoring, or conversation summarization."
        )

    if _has_error(state, "interpreter_json_parse_error", module="interpret"):
        return (
            "I could not reliably understand the structure of the request. Please "
            "rephrase it more directly. I can help with math tutoring, history "
            "tutoring, or conversation summarization."
        )

    if any(getattr(seg, "is_fallback", False) for seg in state.segments):
        return (
            "I could not safely classify the request. Please rephrase it as a neutral "
            "academic tutoring question. I can help with math, history, or conversation "
            "summarization."
        )

    if state.answers:
        return "\n\n".join(answer.answer_text for answer in state.answers)

    if state.decisions:
        rejected_or_clarify = [
            d for d in state.decisions
            if d.decision in {"reject", "clarify"}
        ]

        if rejected_or_clarify:
            messages = []
            for d in rejected_or_clarify:
                reason = d.reason or "This part cannot be handled as a supported tutoring task."
                messages.append(f"- {reason}")

            return (
                "I could not answer the request as a supported tutoring task.\n\n"
                + "\n".join(messages)
                + "\n\nI can help with math tutoring, history tutoring, or conversation summarization."
            )

    if state.errors:
        return (
            "The tutoring system encountered a recoverable processing issue. Please "
            "rephrase the question more directly as a math, history, or conversation "
            "summarization task."
        )

    return (
        "I could not find a supported tutoring task in the request. I can help with "
        "math tutoring, history tutoring, or conversation summarization."
    )


def run(state: TutorState) -> TutorState:
    if _has_error(state, "provider_content_filter", module="interpret"):
        state.final_response = _deterministic_fallback_response(state)
        return state

    client = LLMClient(
        model=state.config["model"],
        api_key=state.config.get("api_key"),
        endpoint=state.config.get("endpoint"),
        api_version=state.config.get("api_version"),
    )

    explanations = _collect_explanations(state)

    context_resolution_json = (
        state.context_resolution.model_dump_json(indent=2)
        if state.context_resolution
        else "{}"
    )

    prompt = ASSEMBLE_USER_TEMPLATE.format(
        raw_input=state.raw_input,
        resolved_input=state.resolved_input or state.raw_input,
        context_resolution_json=context_resolution_json,
        interpretation_note=state.interpretation_note or "",
        segments_json=json.dumps(
            [s.model_dump() for s in state.segments],
            ensure_ascii=False,
            indent=2,
        ),
        decisions_json=json.dumps(
            [d.model_dump() for d in state.decisions],
            ensure_ascii=False,
            indent=2,
        ),
        answers_json=json.dumps(
            [a.model_dump() for a in state.answers],
            ensure_ascii=False,
            indent=2,
        ),
        explanations_json=json.dumps(
            explanations,
            ensure_ascii=False,
            indent=2,
        ),
    )

    try:
        result = client.call_json(
            system_prompt=ASSEMBLE_SYSTEM_PROMPT,
            user_prompt=prompt,
            response_model=AssembleResponse,
        )

        state.final_response = result.response
        return state

    except LLMContentFilterError:
        state.errors.append(
            PipelineError(
                module="assemble",
                error_type="provider_content_filter",
                message="The assemble model call was blocked by the provider content filter.",
                recoverable=True,
            )
        )

    except LLMJSONParseError:
        state.errors.append(
            PipelineError(
                module="assemble",
                error_type="assemble_json_parse_error",
                message="The assemble model returned output that could not be parsed into the expected schema.",
                recoverable=True,
            )
        )

    except LLMProviderError:
        state.errors.append(
            PipelineError(
                module="assemble",
                error_type="llm_provider_error",
                message="The assemble model call failed due to a provider/API error.",
                recoverable=True,
            )
        )

    except Exception as e:
        state.errors.append(
            PipelineError(
                module="assemble",
                error_type="unexpected_error",
                message=f"The assemble module failed unexpectedly: {type(e).__name__}: {e}",
                recoverable=True,
            )
        )

    state.final_response = _deterministic_fallback_response(state)
    return state



