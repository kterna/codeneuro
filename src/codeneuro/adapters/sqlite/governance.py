"""Client-reported test evidence and rule observation persistence."""
from datetime import datetime, timezone
import json

import sqlalchemy as sa

from ...modules.governance import TestReport
from . import schema as s
from .common import Repo, _json


def _report(row):
    return TestReport(row['id'], row['project_id'], row['task_id'],
                      tuple(json.loads(row['paths_json'])), tuple(json.loads(row['command_json'])),
                      row['exit_code'], row['started_at'], row['finished_at'],
                      row['source'], row['recorded_at'], tuple(json.loads(row['test_cases_json']))) if row else None


class GovernanceRepo(Repo):
    def state(self, rule_id):
        return self._one(sa.select(s.rule_validation_state).where(s.rule_validation_state.c.rule_id == rule_id))

    def create_state(self, rule_id, version, half_life_days):
        self.c.execute(s.rule_validation_state.insert().values(rule_id=rule_id,
            evidence_version=version, half_life_days=half_life_days,
            revision_at=datetime.now(timezone.utc).isoformat()))

    def reset_state(self, rule_id, version):
        self.c.execute(s.rule_validation_state.update().where(s.rule_validation_state.c.rule_id == rule_id).values(
            evidence_version=version, revision_at=datetime.now(timezone.utc).isoformat()))

    def test_by_fingerprint(self, task_id, fingerprint):
        return _report(self._one(sa.select(s.test_reports).where(
            s.test_reports.c.task_id == task_id, s.test_reports.c.fingerprint == fingerprint)
            .order_by(s.test_reports.c.id)))

    def test_report(self, report_id):
        return _report(self._one(sa.select(s.test_reports).where(s.test_reports.c.id == report_id)))

    def record_test(self, report, fingerprint):
        self.c.execute(s.test_reports.insert().values(id=report.id, project_id=report.project_id,
            task_id=report.task_id,
            fingerprint=fingerprint, command_json=_json(report.command), paths_json=_json(report.paths),
            exit_code=report.exit_code, started_at=report.started_at,
            finished_at=report.finished_at, recorded_at=report.recorded_at,
            source=report.source, test_cases_json=_json(report.test_cases)))

    def observations(self, rule_id, evidence_version):
        return self._events(rule_id, evidence_version)

    def _events(self, rule_id, evidence_version, check_id=None):
        query = sa.select(s.rule_observations.c.supports, s.rule_observations.c.check_ids_json,
            s.test_reports.c.fingerprint, s.test_reports.c.exit_code, s.test_reports.c.recorded_at).join(
                s.test_reports, s.test_reports.c.id == s.rule_observations.c.test_report_id).where(
                    s.rule_observations.c.rule_id == rule_id,
                    s.rule_observations.c.evidence_version == evidence_version)
        events = {}
        for row in self.c.execute(query):
            if check_id is not None and check_id not in json.loads(row.check_ids_json):
                continue
            prior = events.get(row.fingerprint)
            value = (bool(row.supports), row.exit_code, row.recorded_at)
            if prior:
                value = (prior[0] and value[0], prior[1] or value[1], min(prior[2], value[2]))
            events[row.fingerprint] = value
        return list(events.values())

    def observation(self, rule_id, evidence_version, report_id):
        row = self._one(sa.select(s.rule_observations.c.supports, s.rule_observations.c.reason,
                                 s.rule_observations.c.check_ids_json).where(
            s.rule_observations.c.rule_id == rule_id,
            s.rule_observations.c.evidence_version == evidence_version,
            s.rule_observations.c.test_report_id == report_id))
        return (bool(row['supports']), row['reason'], tuple(json.loads(row['check_ids_json']))) if row else None

    def check_observations(self, rule_id, evidence_version, check_id):
        return self._events(rule_id, evidence_version, check_id)

    def record_review(self, review_id, project_id, rule_id, rule_version, approve, reason, reviewer_id):
        self.c.execute(s.rule_reviews.insert().values(id=review_id, project_id=project_id, rule_id=rule_id,
            rule_version=rule_version, approve=approve, reason=reason, reviewer_id=reviewer_id,
            created_at=datetime.now(timezone.utc).isoformat()))

    def record_observation(self, rule_id, evidence_version, report_id, supports, reason, check_ids):
        from uuid import uuid4
        self.c.execute(s.rule_observations.insert().values(id='obs_' + uuid4().hex,
            rule_id=rule_id, evidence_version=evidence_version, test_report_id=report_id,
            supports=supports, reason=reason, check_ids_json=_json(check_ids),
            created_at=datetime.now(timezone.utc).isoformat()))
