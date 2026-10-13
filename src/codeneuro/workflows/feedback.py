"""Feedback application workflow; domain rules remain in their owning modules."""
from __future__ import annotations

from ..modules.findings import Issue
from ..modules.knowledge import relative_path
from ..modules.tasks import Conflict, ProductError
from ..modules.workspaces import Actor
from .common import _id
from .workspaces import Workspaces


class Feedback(Workspaces):
    def rate_rule(self, actor: Actor, session_id: str, delivery_id: str,
                  rule_id: str, score: int, reason: str = ''):
        if type(score) is not int or not 0 <= score <= 5:
            raise ProductError('Score must be an integer from 0 to 5.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.debug:
                raise ProductError('Debug feedback is not enabled.', 'forbidden')
            version = tx.feedback.delivered_rule(session_id, delivery_id, rule_id)
            if version is None:
                raise ProductError('Only actually delivered Rules can be rated.')
            previous = tx.feedback.prior_feedback(delivery_id, rule_id)
            if previous:
                if previous != (score, reason):
                    raise Conflict('Feedback on this delivery cannot be changed.')
                return {'rule_version': version, 'score': score, 'duplicate': True}
            tx.feedback.record_feedback(session_id, delivery_id, rule_id, version, score, reason)
            tx.audit.record(session.project_id, actor.id, 'rule.rated', rule_id,
                     {'delivery_id': delivery_id, 'version': version, 'score': score})
            return {'rule_version': version, 'score': score, 'duplicate': False}

    def report_issue(self, actor: Actor, session_id: str, issue_type: str,
                     title: str, description: str, file_path: str,
                     related_rule_ids: tuple[str, ...] = (), suggested_action: str = ''):
        relative_path(file_path)
        if not title.strip() or not description.strip():
            raise ProductError('Issue title and description are required.')
        with self.uow.write() as tx:
            session = self._session(tx, actor, session_id)
            if not session.debug:
                raise ProductError('Issue reporting requires a Debug session.', 'forbidden')
            if issue_type == 'conflict' and (not session.task_id or len(set(related_rule_ids)) < 2):
                raise ProductError('A reported conflict needs two distinct Rules in a Task.')
            references = []
            for rule_id in related_rule_ids:
                rule = tx.knowledge.get_rule(rule_id)
                if rule is None or rule.project_id != session.project_id or rule.task_id not in (None, session.task_id):
                    raise ProductError('Issue references a Rule outside the current scope.')
                references.append((rule.id, rule.version))
            item = Issue(_id('issue'), session.project_id, session.id,
                         issue_type, title, description, file_path, related_rule_ids,
                         suggested_action, tuple(references))
            tx.feedback.record_issue(item)
            tx.audit.record(session.project_id, actor.id, 'issue.reported', item.id,
                     {'related_rule_ids': list(related_rule_ids)})
            return item
