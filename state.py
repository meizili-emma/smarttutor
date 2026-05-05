from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ConversationContext(BaseModel):
    recent_turns: List[Dict[str, Any]] = Field(default_factory=list)
    active_thread: Dict[str, Any] = Field(default_factory=dict)
    session_summary: Dict[str, Any] = Field(default_factory=dict)
    relevant_learning_records: List[Dict[str, Any]] = Field(default_factory=list)


class ContextResolution(BaseModel):
    relation_to_previous: str = Field(
        description=(
            "standalone | follow_up | continuation | correction | clarification | "
            "summary_request | unrelated_new_topic"
        )
    )
    needs_previous_context: bool = False
    referenced_turn_ids: List[str] = Field(default_factory=list)
    referenced_topic: Optional[str] = None
    resolved_input: str
    resolution_confidence: str = Field(description="high | medium | low")
    reason: str = ""

    # Used only when relation_to_previous == summary_request.
    summary_scope: Optional[str] = Field(
        default=None,
        description=(
            "latest_turn | active_thread | recent_session | whole_session | "
            "domain_filtered | null"
        ),
    )
    summary_domain_filter: Optional[str] = Field(
        default=None,
        description="math | history | summary | null",
    )
    

class Segment(BaseModel):
    segment_id: str
    original_text: str
    structure_role: str = Field(
        description="standalone_task | independent_subtask | condition | branch | context | meta_instruction"
    )
    inferred_domain: str = Field(
        description="math | history | summary | other | ambiguous | unknown"
    )
    constraints: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    # Fallback/error-aware interpretation support.
    is_fallback: bool = False
    fallback_reason: Optional[str] = Field(
        default=None,
        description=(
            "Reason this segment was created as a fallback, e.g. "
            "provider_content_filter | interpreter_json_parse_error | llm_provider_error | unexpected_error"
        ),
    )


class PolicyDecision(BaseModel):
    segment_id: str
    decision: str = Field(
        description="accept | transform | abstract | reject | clarify"
    )
    reason: str = ""
    intent_type: str = Field(
        description="academic | applied_practical | non_academic | unsafe | ambiguous"
    )
    can_be_handled_as_tutoring_task: bool
    handled_domain: Optional[str] = Field(
        default=None,
        description="math | history | summary | null"
    )
    transformed_task_text: Optional[str] = None
    abstracted_task_text: Optional[str] = None
    explain_handling: bool = True


class Task(BaseModel):
    task_id: str
    segment_id: str
    task_type: str = Field(description="math | history | summary")
    task_text: str
    solver_name: str = Field(description="math_solver | history_solver | summary_solver")
    style: str = Field(description="guided | step_by_step | concise | mixed")
    constraints: List[str] = Field(default_factory=list)

    conversation_context: Optional[ConversationContext] = None
    context_resolution: Optional[ContextResolution] = None
    resolved_input: Optional[str] = None


class AnswerRecord(BaseModel):
    task_id: str
    segment_id: str
    task_type: str
    answer_text: str
    solver_notes: Optional[str] = None


class VerificationRecord(BaseModel):
    check_type: str
    ok: bool
    segment_id: Optional[str] = None
    task_id: Optional[str] = None
    issue: Optional[str] = None


class CoverageResult(BaseModel):
    ok: bool
    missing_segment_ids: List[str] = Field(default_factory=list)
    unexpected_answer_segment_ids: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class PipelineError(BaseModel):
    module: str = Field(
        description="Module where the error occurred, e.g. interpret | policy | normalize | plan | solve | verify | coverage | assemble | controller"
    )
    error_type: str = Field(
        description=(
            "provider_content_filter | interpreter_json_parse_error | "
            "llm_provider_error | schema_validation_error | unexpected_error"
        )
    )
    message: str = ""
    recoverable: bool = True


class TutorState(BaseModel):
    raw_input: str
    config: Dict[str, Any] = Field(default_factory=dict)
    memory: Dict[str, Any] = Field(default_factory=dict)

    conversation_context: Optional[ConversationContext] = None
    context_resolution: Optional[ContextResolution] = None
    resolved_input: Optional[str] = None

    structure_type: Optional[str] = None
    interpretation_note: Optional[str] = None
    segments: List[Segment] = Field(default_factory=list)

    decisions: List[PolicyDecision] = Field(default_factory=list)

    tasks: List[Task] = Field(default_factory=list)
    answers: List[AnswerRecord] = Field(default_factory=list)

    verification_records: List[VerificationRecord] = Field(default_factory=list)
    coverage: Optional[CoverageResult] = None

    errors: List[PipelineError] = Field(default_factory=list)

    final_response: str = ""