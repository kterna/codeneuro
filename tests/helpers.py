"""Explicit fixture topics and evidence; never product defaults or invented host results."""
from functools import partial
from codeneuro.adapters.sqlite.uow import initialize_database

from codeneuro.modules.context import ContextQuery
from codeneuro.modules.knowledge import Priority

LEVELS = tuple(Priority)
TOPICS = ('test-contracts',)
REVIEW = {'kind': 'review', 'basis': 'Explicitly reviewed synthetic fixture contract'}
PLAN = {'kind': 'test', 'checks': [
    {'id': 'contract', 'clause_indexes': [0], 'test_ids': ['contract-test']},
]}
CASES = ({'test_id': 'contract-test', 'status': 'passed'},)


def file_query(files, *, priorities=LEVELS, **kwargs):
    return ContextQuery(priorities=priorities, files=files, **kwargs)


def configure_fixture(product, human, project_ids):
    for project_id in project_ids:
        product.topics.create_topic(human, TOPICS[0], 'Fixture contracts',
            'Only deterministic test fixture contracts', 'Initialize fixture vocabulary', project_id=project_id)
    product.knowledge.create_rule = partial(product.knowledge.create_rule,
        topics=TOPICS, validation_spec=REVIEW, priority_reason='Fixture irreversible data-loss constraint')
    product.governance.create_task_rule = partial(product.governance.create_task_rule,
        topics=TOPICS, validation_spec=PLAN, priority_reason='Fixture irreversible data-loss constraint')
    product.governance.report_test = partial(product.governance.report_test, test_cases=CASES)
    product.governance.observe_rule = partial(product.governance.observe_rule, check_ids=('contract',))
    product.context.record_finding = partial(product.context.record_finding, topics=TOPICS)


def create_scope(product, actor, project_id='p', title='Overall goal', task_title='Implementation'):
    requirement = product.requirements.manage_requirement(actor, project_id, 'create',
        changes={'title': title, 'text': 'Business objective and overall acceptance'})
    task = product.workspaces.create_task(actor, project_id, requirement.id, task_title)
    return requirement, task


def propose_review(product, agent, task_id, target_id, title, points, patterns, priority, reason):
    with product.workspaces.uow.read() as tx:
        target = tx.knowledge.get_rule(target_id)
    candidate = product.governance.create_task_rule(agent, task_id, title, points, patterns,
        reason, priority=priority, validation_spec=REVIEW)['rule']
    return product.knowledge.propose_contract(agent, task_id, target_id, target.version,
                                             candidate['id'], candidate['version'], reason)
