import hashlib
import json
import uuid
from datetime import datetime, timezone


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex}"


def dump(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )


def load(value, default=None):
    if value is None:
        return default
    return json.loads(value) if isinstance(value, (str, bytes)) else value


def digest(value):
    return hashlib.sha256(
        value.encode("utf-8") if isinstance(value, str) else value
    ).hexdigest()


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value):
    return value.isoformat() + "Z" if isinstance(value, datetime) else value
