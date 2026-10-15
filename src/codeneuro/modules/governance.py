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
    test_cases: tuple[dict, ...] = ()


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
    if not command or any(not part or len(part) > 2000 for part in command):
        raise ProductError('A bounded argv command is required; source paths are optional.')
    if type(exit_code) is not int:
        raise ProductError('Test exit_code must be an actual integer supplied by the client.')
    try:
        start = datetime.fromisoformat(started_at)
        finish = datetime.fromisoformat(finished_at)
        if start.tzinfo is None or finish.tzinfo is None or finish < start:
            raise ValueError
    except ValueError:
        raise ProductError('Use timezone-aware, ordered test timestamps.') from None


def validate_plan(spec: dict | None, clause_count: int):
    if not isinstance(spec, dict) or spec.get('kind') not in ('test', 'review'):
        raise ProductError('An explicit test or review validation plan is required.')
    if spec['kind'] == 'review':
        if set(spec) != {'kind', 'basis'} or not isinstance(spec['basis'], str) or not spec['basis'].strip():
            raise ProductError('Review plans require their normative basis.')
        return
    checks = spec.get('checks')
    if set(spec) != {'kind', 'checks'} or not isinstance(checks, list) or not 1 <= len(checks) <= 50:
        raise ProductError('Test plans require 1–50 explicit checks.')
    identities, covered = set(), set()
    for check in checks:
        if not isinstance(check, dict) or set(check) != {'id', 'clause_indexes', 'test_ids'}:
            raise ProductError('Each check requires id, clause_indexes and test_ids.')
        identity, clauses, tests = check['id'], check['clause_indexes'], check['test_ids']
        if not isinstance(identity, str) or not identity.strip() or identity in identities:
            raise ProductError('Validation check IDs must be distinct and non-empty.')
        if not isinstance(clauses, list) or not clauses or any(type(i) is not int or not 0 <= i < clause_count for i in clauses):
            raise ProductError('Validation checks must reference existing clause indexes.')
        if not isinstance(tests, list) or not tests or any(not isinstance(t, str) or not t.strip() for t in tests) or len(set(tests)) != len(tests):
            raise ProductError('Checks require distinct host-reported test identifiers.')
        identities.add(identity)
        covered.update(clauses)
    if covered != set(range(clause_count)):
        raise ProductError('Every clause must be covered by the validation plan.')


def validate_cases(cases: tuple[dict, ...]):
    if not 1 <= len(cases) <= 500:
        raise ProductError('Report 1–500 actual test-case results.')
    seen = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {'test_id', 'status'}:
            raise ProductError('Test cases require test_id and status.')
        identity = case['test_id']
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ProductError('Test identifiers must be distinct and non-empty.')
        if case['status'] not in ('passed', 'failed', 'skipped'):
            raise ProductError('Unsupported test-case status.')
        seen.add(identity)


def covered_checks(spec: dict, report: TestReport, check_ids: tuple[str, ...], supports: bool):
    if spec.get('kind') != 'test' or not check_ids or len(set(check_ids)) != len(check_ids):
        raise ProductError('Explicit test-plan check IDs are required.')
    checks = {item['id']: item for item in spec['checks']}
    if set(check_ids) - checks.keys():
        raise ProductError('Unknown validation check.')
    cases = {case['test_id']: case['status'] for case in report.test_cases}
    for key in check_ids:
        expected = checks[key]['test_ids']
        if not all(identity in cases for identity in expected):
            raise ProductError('Report must cover the declared tests, not merely the same Task or path.')
        if supports and (report.exit_code != 0 or any(cases[identity] != 'passed' for identity in expected)):
            raise ProductError('Failed or skipped tests cannot support a Rule.')
