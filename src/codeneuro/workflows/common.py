"""Identifiers, explicit idempotency and bounded history parameters."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4
from ..modules.tasks import Conflict, ProductError


def _id(prefix):
    return prefix + '_' + uuid4().hex


def _now():
    return datetime.now(timezone.utc).isoformat()


def _fingerprint(value):
    payload = asdict(value) if is_dataclass(value) else value
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, default=str).encode()).hexdigest()


def replay(tx, project_id, operation, request_id, payload):
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 128):
        raise ProductError('request_id must contain 1–128 characters.')
    fingerprint = _fingerprint(payload)
    previous = tx.workspaces.request(project_id, operation, request_id)
    if previous and previous[0] != fingerprint:
        raise Conflict('request_id already used for different input in this project and operation.')
    return fingerprint, previous[1] if previous else None


def page_cursor(identity, resource, project_id, requirement_id=None, statuses=None):
    scope = _fingerprint([resource, project_id, requirement_id, sorted(statuses) if statuses is not None else None])
    return identity + '.' + scope


def cursor_id(cursor, resource, project_id, requirement_id=None, statuses=None):
    if cursor is None:
        return None
    identity, separator, _ = cursor.rpartition('.')
    if not separator or not identity or cursor != page_cursor(identity, resource, project_id, requirement_id, statuses):
        raise ProductError('The cursor does not match this resource, project and list filters; restart the list.')
    return identity


def history_page(fetch, cursor, limit):
    if type(limit) is not int or not 1 <= limit <= 100 or (cursor is not None and (type(cursor) is not int or cursor < 1)):
        raise ProductError('Use a positive history_cursor and history_limit of 1–100.')
    rows = fetch(cursor, limit + 1)
    return {'history': rows[:limit], 'next_history_cursor': rows[limit - 1]['version'] if len(rows) > limit else None}
