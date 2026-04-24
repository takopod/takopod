MODEL_OPTIONS: list[dict[str, str]] = [
    {"value": "claude-sonnet-4-6:low",    "label": "Claude Sonnet 4.6 (low)",    "model_id": "claude-sonnet-4-6", "effort": "low"},
    {"value": "claude-sonnet-4-6:medium", "label": "Claude Sonnet 4.6 (medium)", "model_id": "claude-sonnet-4-6", "effort": "medium"},
    {"value": "claude-sonnet-4-6:high",   "label": "Claude Sonnet 4.6 (high)",   "model_id": "claude-sonnet-4-6", "effort": "high"},
    {"value": "claude-sonnet-4-6:max",    "label": "Claude Sonnet 4.6 (max)",    "model_id": "claude-sonnet-4-6", "effort": "max"},
    {"value": "claude-opus-4-6:low",      "label": "Claude Opus 4.6 (low)",      "model_id": "claude-opus-4-6",   "effort": "low"},
    {"value": "claude-opus-4-6:medium",   "label": "Claude Opus 4.6 (medium)",   "model_id": "claude-opus-4-6",   "effort": "medium"},
    {"value": "claude-opus-4-6:high",     "label": "Claude Opus 4.6 (high)",     "model_id": "claude-opus-4-6",   "effort": "high"},
    {"value": "claude-opus-4-6:max",      "label": "Claude Opus 4.6 (max)",      "model_id": "claude-opus-4-6",   "effort": "max"},
]


def get_model_options() -> list[dict[str, str]]:
    return MODEL_OPTIONS
