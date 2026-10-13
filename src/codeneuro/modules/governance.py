"""Pure agent-rule evidence policy; reports are client claims, not Hub-run tests."""
from dataclasses import dataclass
from datetime import datetime, timezone

from .tasks import Conflict, ProductError


@dataclass(frozen=True)
class TestReport:
    id: str
    session_id: str
    project_id: str
    task_id: str
    paths: tuple[str, ...]
    command: tuple[str, ...]
    exit_code: int
    started_at: str
    finished_at: str
    source: str = 'client_reported'
    recorded_at: str = ''  # Hub receipt time, unlike client-attested test timestamps.


@dataclass(frozen=True)
class EvidenceStats:
    support_count: int
    contradiction_count: int
    confidence: float
    effective_confidence: float
    stage: str
    evidence_version: int


def assess(rule_version: int, evidence_version: int, half_life_days: int,
           observations: list[tuple[bool, int, str]], *, at: datetime | None = None) -> EvidenceStats:
    now = at or datetime.now(timezone.utc)
    positive = sum(bool(supports) and exit_code == 0 for supports, exit_code, _ in observations)
    negative = sum(not supports for supports, _, _ in observations)
    confidence = (1 + positive) / (2 + positive + negative)
    latest = max((datetime.fromisoformat(stamp) for _, _, stamp in observations), default=now)
    age = max(0.0, (now - latest).total_seconds() / 86400)
    effective = confidence * (0.5 ** (age / half_life_days))
    stage = 'validated' if positive >= 2 and negative == 0 else 'observing'
    return EvidenceStats(positive, negative, round(confidence, 6), round(effective, 6), stage, evidence_version)


def require_activation(stats: EvidenceStats):
    if stats.stage != 'validated' or stats.effective_confidence < 0.6:
        raise Conflict('Activation requires two distinct fresh successful client-reported tests, '
                       'no contradictions and effective confidence >= 0.6.')


def validate_test_report(command: tuple[str, ...], paths: tuple[str, ...],
                         started_at: str, finished_at: str, exit_code: int):
    if not command or not paths or any(not part or len(part) > 2000 for part in command):
        raise ProductError('A bounded argv command and affected paths are required.')
    if type(exit_code) is not int:
        raise ProductError('Test exit_code must be an actual integer supplied by the client.')
    try:
        start = datetime.fromisoformat(started_at)
        finish = datetime.fromisoformat(finished_at)
        if start.tzinfo is None or finish.tzinfo is None or finish < start:
            raise ValueError
    except ValueError:
        raise ProductError('Use timezone-aware, ordered test timestamps.') from None
