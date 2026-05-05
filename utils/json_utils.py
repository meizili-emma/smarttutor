import json
import re
from typing import Any


def extract_json_object(text: str) -> Any:
    """
    Extract the first top-level JSON object from model output.
    The prompts ask for strict JSON, but this gives a small safety net.
    """
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"Could not find JSON object in model output:\n{text}")

    return json.loads(match.group(0))