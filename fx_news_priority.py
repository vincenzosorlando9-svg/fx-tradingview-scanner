"""Priority triage for approved FX news headlines; never generates orders."""
from datetime import datetime, timezone

def parse_utc(value):
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except (TypeError, ValueError):
        return None
