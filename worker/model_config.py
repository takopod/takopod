def parse_model_spec(spec: str | None) -> tuple[str | None, str | None]:
    if not spec:
        return None, None
    parts = spec.rsplit(":", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return parts[0], None
