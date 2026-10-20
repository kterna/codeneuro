"""Actual-delivery feedback and explicit project/task issues."""
from ..modules.findings import Issue
from ..modules.knowledge import relative_path
from ..modules.tasks import Conflict, ProductError
from .common import _id
from .workspaces import Workspaces


class Feedback(Workspaces):
    def rate_rule(self, actor, delivery_id, rule_id, score, reason=''):
        if type(score) is not int or not 0 <= score <= 5:
            raise ProductError('Score must be an integer from 0 to 5.')
        with self.uow.write() as tx:
            scope = tx.context.delivery_scope(delivery_id)
            version = tx.feedback.delivered_rule(delivery_id, rule_id)
            if not scope or version is None:
                raise ProductError('Only actually delivered Rules can be rated.', 'not_found')
            previous = tx.feedback.prior_feedback(delivery_id, rule_id)
            if previous:
                if previous != (score, reason):
                    raise Conflict('Feedback on this delivery cannot be changed.')
                return {'rule_version': version, 'score': score, 'duplicate': True}
            tx.feedback.record_feedback(delivery_id, rule_id, version, score, reason)
            tx.audit.record(scope['project_id'], actor.id, 'rule.rated', rule_id,
                            {'delivery_id': delivery_id, 'version': version, 'score': score})
            return {'rule_version': version, 'score': score, 'duplicate': False}

    def report_issue(self, actor, project_id, issue_type, title, description, file_path=None,
                     related_rule_ids=(), suggested_action='', *, task_id=None):
        if file_path is not None:
            relative_path(file_path)
        if not title.strip() or not description.strip():
            raise ProductError('Issue title and description are required.')
        with self.uow.write() as tx:
            tx.workspaces.project_revision(project_id)
            if task_id:
                self._task(tx, task_id, project_id)
            if issue_type == 'conflict' and (not task_id or len(set(related_rule_ids)) < 2):
                raise ProductError('A reported conflict needs a Task and two distinct Rules.')
            references = []
            for rule_id in related_rule_ids:
                rule = tx.knowledge.get_rule(rule_id)
                if rule is None or rule.project_id != project_id or rule.task_id not in (None, task_id):
                    raise ProductError('Issue references a Rule outside the selected scope.')
                references.append((rule.id, rule.version))
            item = Issue(_id('issue'), project_id, task_id, issue_type, title, description,
                         file_path, related_rule_ids, suggested_action, tuple(references))
            tx.feedback.record_issue(item)
            tx.audit.record(project_id, actor.id, 'issue.reported', item.id,
                            {'task_id': task_id, 'related_rule_ids': list(related_rule_ids)})
            return item
