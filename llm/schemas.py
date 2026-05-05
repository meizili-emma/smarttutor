from typing import List, Optional
from pydantic import BaseModel, Field


class ContextResolutionResponse(BaseModel):
    relation_to_previous: str
    needs_previous_context: bool = False
    referenced_turn_ids: List[str] = Field(default_factory=list)
    referenced_topic: Optional[str] = None
    resolved_input: str
    resolution_confidence: str = "medium"
    reason: str = ""
    summary_scope: Optional[str] = None
    summary_domain_filter: Optional[str] = None


class ActiveThreadUpdateResponse(BaseModel):
    thread_id: str
    domain: str
    topic_title: str
    latest_user_goal: str
    latest_answer_summary: str
    last_answer_outline: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    status: str = "active"


class SessionSummaryResponse(BaseModel):
    brief: str
    main_topics: List[str] = Field(default_factory=list)
    recent_focus: Optional[str] = None
    user_difficulties: List[str] = Field(default_factory=list)


class SegmentPayload(BaseModel):
    segment_id: str
    original_text: str
    structure_role: str
    inferred_domain: str
    constraints: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class InterpretResponse(BaseModel):
    structure_type: str
    interpretation_note: str
    segments: List[SegmentPayload]


class PolicyDecisionPayload(BaseModel):
    segment_id: str
    decision: str
    reason: Optional[str] = ""
    intent_type: str
    can_be_handled_as_tutoring_task: bool
    handled_domain: Optional[str] = None
    transformed_task_text: Optional[str] = None
    abstracted_task_text: Optional[str] = None
    explain_handling: bool = True


class PolicyResponse(BaseModel):
    decisions: List[PolicyDecisionPayload]


class NormalizedSegmentPayload(BaseModel):
    segment_id: str
    normalized_text: str


class NormalizeResponse(BaseModel):
    normalized_segments: List[NormalizedSegmentPayload]


class SolveResponse(BaseModel):
    answer_text: str
    solver_notes: Optional[str] = None


class MemoryRecordResponse(BaseModel):
    topic_title: str
    learning_summary: str
    key_concepts: List[str] = Field(default_factory=list)


class VerifyRecordPayload(BaseModel):
    check_type: str
    ok: bool
    segment_id: Optional[str] = None
    task_id: Optional[str] = None
    issue: Optional[str] = None


class VerifyResponse(BaseModel):
    records: List[VerifyRecordPayload]


class AssembleResponse(BaseModel):
    response: str