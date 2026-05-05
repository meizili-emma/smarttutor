def debug_snapshot(state) -> dict:
    def safe_model_dump(obj):
        if obj is None:
            return None
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        return obj

    return {
        "raw_input": getattr(state, "raw_input", ""),
        "resolved_input": getattr(state, "resolved_input", None),

        "context_resolution": safe_model_dump(
            getattr(state, "context_resolution", None)
        ),

        "conversation_context_preview": safe_model_dump(
            getattr(state, "conversation_context", None)
        ),

        "structure_type": getattr(state, "structure_type", None),
        "interpretation_note": getattr(state, "interpretation_note", None),

        "segments": [
            safe_model_dump(item)
            for item in getattr(state, "segments", [])
        ],

        "decisions": [
            safe_model_dump(item)
            for item in getattr(state, "decisions", [])
        ],

        "tasks": [
            safe_model_dump(item)
            for item in getattr(state, "tasks", [])
        ],

        "answers": [
            safe_model_dump(item)
            for item in getattr(state, "answers", [])
        ],

        "verification_records": [
            safe_model_dump(item)
            for item in getattr(state, "verification_records", [])
        ],

        "coverage": safe_model_dump(getattr(state, "coverage", None)),

        "errors": [
            safe_model_dump(item)
            for item in getattr(state, "errors", [])
        ],

        "final_response": getattr(state, "final_response", ""),
    }