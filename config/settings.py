SUPPORTED_DOMAINS = {"math", "history", "summary"}

STYLE_PROFILES = {
    "guided": {
        "ask_guiding_question": True,
        "detail_level": "medium",
        "max_guiding_questions": 1,
        "description": "Ask at most one short guiding question, then explain."
    },
    "step_by_step": {
        "ask_guiding_question": False,
        "detail_level": "high",
        "max_guiding_questions": 0,
        "description": "Explain with explicit steps."
    },
    "concise": {
        "ask_guiding_question": False,
        "detail_level": "low",
        "max_guiding_questions": 0,
        "description": "Answer directly with minimal explanation."
    },
    "mixed": {
        "ask_guiding_question": False,
        "detail_level": "medium",
        "max_guiding_questions": 0,
        "description": "Balanced tutoring style."
    },
}

DEFAULTS = {
    "model": "gpt-4o-mini",
    "style": "mixed",
    "debug": False,
    "max_retries": 1,
    "enable_llm_verify": False,
}