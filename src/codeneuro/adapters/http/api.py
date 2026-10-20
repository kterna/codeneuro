"""HTTP resource mapping; business transitions live in the shared workflows."""
from dataclasses import asdict
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...modules.tasks import ProductError
from ...modules.knowledge import Priority
from ...modules.workspaces import Actor
from ...workflows.product import Product
from ..mcp.inputs import RequirementChanges, TaskChanges, Source


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProjectInput(Input):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=500)


class ReviewInput(Input):
    approve: bool
    reason: str = Field(min_length=1)


class StatusInput(Input):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1)


class VersionedInput(Input):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1)


class CreateRequirement(Input):
    changes: RequirementChanges
    request_id: str | None = None
    source: Source | None = None


class UpdateRequirement(VersionedInput):
    changes: RequirementChanges


class CreateTask(Input):
    requirement_id: str
    changes: TaskChanges
    request_id: str | None = None
    source: Source | None = None


class UpdateTask(VersionedInput):
    changes: TaskChanges


class TopicInput(Input):
    key: str
    name: str
    description: str
    reason: str = Field(min_length=1)


class TopicUpdateInput(VersionedInput):
    name: str | None = None
    description: str | None = None


class RuleReviewInput(VersionedInput):
    approve: bool


class FindingUpdateInput(VersionedInput):
    topics: list[str] | None = None
    resolve: bool = False


class ClassifyInput(VersionedInput):
    topics: list[str]
    patterns: list[str] | None = None
    priority: Priority | None = None
    is_global: bool = False
    priority_reason: str = ''


def create_router(product: Product):
    router = APIRouter(prefix='/api')
    web_actor = Actor('web', 'human')

    def call(method, *args, **kwargs):
        try:
            value = method(web_actor, *args, **kwargs)
            return asdict(value) if hasattr(value, '__dataclass_fields__') else value
        except ProductError as error:
            status = {'conflict': 409, 'forbidden': 403, 'not_found': 404}.get(error.code, 400)
            raise HTTPException(status_code=status, detail={'code': error.code, 'message': str(error)}) from error

    def detail(method, project_id, identity):
        result = call(method, project_id, 'get', identity)
        return {key: value for key, value in result.items() if key not in ('history', 'next_history_cursor')}

    def versions(method, project_id, identity, cursor, limit):
        result = call(method, project_id, 'get', identity, history_cursor=cursor, history_limit=limit)
        return {'items': result['history'], 'next_cursor': result['next_history_cursor']}

    @router.get('/projects')
    def projects():
        return call(product.workspaces.list_projects)

    @router.post('/projects')
    def register(body: ProjectInput):
        return call(product.workspaces.register_project, body.id, body.name)

    @router.delete('/projects/{project_id}')
    def remove_project(project_id: str):
        return call(product.workspaces.delete_project, project_id)

    @router.get('/projects/{project_id}/requirements')
    def requirements(project_id: str, statuses: list[str] | None = Query(None), cursor: str | None = None,
                     limit: int = Query(20, ge=1, le=100)):
        return call(product.requirements.manage_requirement, project_id, 'list',
                    statuses=tuple(statuses) if statuses is not None else None, cursor=cursor, limit=limit)

    @router.post('/projects/{project_id}/requirements')
    def create_requirement(project_id: str, body: CreateRequirement):
        return call(product.requirements.manage_requirement, project_id, 'create',
                    changes=body.changes.model_dump(exclude_unset=True), request_id=body.request_id,
                    source=body.source.model_dump(exclude_unset=True) if body.source else None)

    @router.get('/projects/{project_id}/requirements/{requirement_id}')
    def requirement(project_id: str, requirement_id: str):
        return detail(product.requirements.manage_requirement, project_id, requirement_id)

    @router.get('/projects/{project_id}/requirements/{requirement_id}/versions')
    def requirement_versions(project_id: str, requirement_id: str, cursor: int | None = Query(None, ge=1),
                             limit: int = Query(20, ge=1, le=100)):
        return versions(product.requirements.manage_requirement, project_id, requirement_id, cursor, limit)

    @router.patch('/projects/{project_id}/requirements/{requirement_id}')
    def update_requirement(project_id: str, requirement_id: str, body: UpdateRequirement):
        return call(product.requirements.manage_requirement, project_id, 'update', requirement_id,
                    body.expected_version, body.changes.model_dump(exclude_unset=True), body.reason)

    @router.delete('/projects/{project_id}/requirements/{requirement_id}')
    def delete_requirement(project_id: str, requirement_id: str, body: VersionedInput):
        return call(product.requirements.manage_requirement, project_id, 'delete', requirement_id,
                    body.expected_version, reason=body.reason)

    @router.get('/projects/{project_id}/requirements/{requirement_id}/tasks')
    def requirement_tasks(project_id: str, requirement_id: str, statuses: list[str] | None = Query(None),
                          cursor: str | None = None, limit: int = Query(20, ge=1, le=100)):
        return call(product.workspaces.manage_task, project_id, 'list', requirement_id=requirement_id,
                    statuses=tuple(statuses) if statuses is not None else None, cursor=cursor, limit=limit)

    @router.get('/projects/{project_id}/tasks')
    def tasks(project_id: str, requirement_id: str | None = None, statuses: list[str] | None = Query(None),
              cursor: str | None = None, limit: int = Query(20, ge=1, le=100)):
        return call(product.workspaces.manage_task, project_id, 'list', requirement_id=requirement_id,
                    statuses=tuple(statuses) if statuses is not None else None, cursor=cursor, limit=limit)

    @router.post('/projects/{project_id}/tasks')
    def create_task(project_id: str, body: CreateTask):
        return call(product.workspaces.manage_task, project_id, 'create', requirement_id=body.requirement_id,
                    changes=body.changes.model_dump(exclude_unset=True), request_id=body.request_id,
                    source=body.source.model_dump(exclude_unset=True) if body.source else None)

    @router.get('/projects/{project_id}/tasks/{task_id}')
    def task(project_id: str, task_id: str):
        return detail(product.workspaces.manage_task, project_id, task_id)

    @router.get('/projects/{project_id}/tasks/{task_id}/versions')
    def task_versions(project_id: str, task_id: str, cursor: int | None = Query(None, ge=1),
                      limit: int = Query(20, ge=1, le=100)):
        return versions(product.workspaces.manage_task, project_id, task_id, cursor, limit)

    @router.patch('/projects/{project_id}/tasks/{task_id}')
    def update_task(project_id: str, task_id: str, body: UpdateTask):
        return call(product.workspaces.manage_task, project_id, 'update', task_id,
                    body.expected_version, body.changes.model_dump(exclude_unset=True), body.reason)

    @router.delete('/projects/{project_id}/tasks/{task_id}')
    def delete_task(project_id: str, task_id: str, body: VersionedInput):
        return call(product.workspaces.manage_task, project_id, 'delete', task_id, body.expected_version, reason=body.reason)

    @router.get('/projects/{project_id}/deliveries/{delivery_id}')
    def delivery(project_id: str, delivery_id: str):
        return call(product.context.get_delivery, delivery_id, project_id=project_id)

    @router.post('/projects/{project_id}/proposals/{proposal_id}/review')
    def review(project_id: str, proposal_id: str, body: ReviewInput):
        return call(product.knowledge.review_contract, project_id, proposal_id, body.approve, body.reason)

    @router.get('/projects/{project_id}/topics')
    def list_topics(project_id: str, query: str = '', include_deleted: bool = False,
                    cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
        return call(product.topics.list_topics, project_id, query, include_deleted, cursor, limit)

    @router.post('/projects/{project_id}/topics')
    def create_topic(project_id: str, body: TopicInput):
        return call(product.topics.create_topic, body.key, body.name, body.description, body.reason, project_id=project_id)

    @router.post('/projects/{project_id}/topics/enable')
    def enable_topics(project_id: str, body: StatusInput):
        return call(product.topics.enable_query, project_id, body.expected_revision, body.reason)

    @router.get('/projects/{project_id}/topics/{key}')
    def get_topic(project_id: str, key: str, include_usage: bool = False):
        return call(product.topics.get_topic, project_id, key, include_usage)

    @router.patch('/projects/{project_id}/topics/{key}')
    def update_topic(project_id: str, key: str, body: TopicUpdateInput):
        return call(product.topics.update_topic, key, body.expected_version, body.reason,
                    body.name, body.description, project_id=project_id)

    @router.delete('/projects/{project_id}/topics/{key}')
    def delete_topic(project_id: str, key: str, body: VersionedInput):
        return call(product.topics.delete_topic, key, body.expected_version, body.reason, project_id=project_id)

    @router.post('/projects/{project_id}/rules/{rule_id}/review')
    def review_rule(project_id: str, rule_id: str, body: RuleReviewInput):
        return call(product.governance.review_task_rule, project_id, rule_id, body.expected_version, body.approve, body.reason)

    @router.post('/projects/{project_id}/rules/{rule_id}/classify')
    def classify_legacy_rule(project_id: str, rule_id: str, body: ClassifyInput):
        return call(product.knowledge.classify_legacy_rule, project_id, rule_id, body.expected_version,
                    tuple(body.topics), body.reason, tuple(body.patterns) if body.patterns is not None else None,
                    body.priority, body.is_global, body.priority_reason)

    @router.patch('/projects/{project_id}/findings/{finding_id}')
    def update_finding(project_id: str, finding_id: str, body: FindingUpdateInput):
        return call(product.context.update_finding, finding_id, body.expected_version, body.reason,
                    tuple(body.topics) if body.topics is not None else None, body.resolve, project_id=project_id)

    @router.get('/projects/{project_id}/ledger')
    def ledger(project_id: str):
        return call(product.ledger.project, project_id)

    @router.get('/projects/{project_id}/tree')
    def tree(project_id: str, worktree_id: str | None = None):
        return call(product.ledger.scope_tree, project_id, worktree_id)

    @router.get('/projects/{project_id}/inspect')
    def inspect(project_id: str, path: str, priorities: list[Priority] = Query(...), task_id: str | None = None):
        return call(product.ledger.inspect_path, project_id, path, tuple(priorities), task_id)

    @router.get('/projects/{project_id}/events')
    def events(project_id: str, limit: int = Query(100, ge=1, le=100), before: int | None = Query(None, ge=1)):
        return call(product.ledger.events, project_id, limit, before)

    return router
