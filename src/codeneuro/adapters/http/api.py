"""Web API; only parameter mapping, never business state transitions."""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ...modules.tasks import ProductError, TaskStatus
from ...modules.knowledge import Priority
from ...modules.workspaces import Actor
from ...workflows.product import Product


class IntakeInput(BaseModel):
    text: str = Field(min_length=1)
    request_id: str = Field(min_length=1, max_length=128)
    task_id: str | None = None
    title: str | None = None


class ProjectInput(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=500)


class ReviewInput(BaseModel):
    approve: bool
    reason: str = Field(min_length=1)


class StatusInput(BaseModel):
    expected_revision: int = Field(ge=0)
    reason: str = Field(min_length=1)


class ArchiveInput(BaseModel):
    expected_version: int = Field(ge=1)
    summary: str = Field(min_length=1)


class TransitionInput(StatusInput):
    status: TaskStatus


class TopicInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str
    name: str
    description: str
    reason: str = Field(min_length=1)


class VersionedInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: int = Field(ge=1)
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
            value = method(*args, **kwargs)
            return asdict(value) if hasattr(value, '__dataclass_fields__') else value
        except ProductError as error:
            status = {'conflict': 409, 'forbidden': 403, 'not_found': 404}.get(error.code, 400)
            raise HTTPException(status_code=status, detail={'code': error.code, 'message': str(error)}) from error

    @router.get('/projects')
    def projects():
        return call(product.workspaces.list_projects, web_actor)

    @router.post('/projects')
    def register(body: ProjectInput):
        return call(product.workspaces.register_project, web_actor, body.id, body.name)

    @router.delete('/projects/{project_id}')
    def remove_project(project_id: str):
        return call(product.workspaces.delete_project, web_actor, project_id)

    @router.get('/projects/{project_id}/tasks')
    def tasks(project_id: str):
        return call(product.workspaces.list_tasks, web_actor, project_id)

    @router.post('/projects/{project_id}/tasks/{task_id}/pause')
    def pause(project_id: str, task_id: str, body: StatusInput):
        return call(product.workspaces.pause_task, web_actor, project_id,
                    task_id, body.expected_revision, body.reason)

    @router.post('/projects/{project_id}/tasks/{task_id}/resume')
    def resume(project_id: str, task_id: str, body: StatusInput):
        return call(product.workspaces.resume_task, web_actor, project_id,
                    task_id, body.expected_revision, body.reason)

    @router.post('/projects/{project_id}/tasks/{task_id}/transition')
    def transition(project_id: str, task_id: str, body: TransitionInput):
        return call(product.workspaces.transition_task, web_actor, project_id,
                    task_id, body.expected_revision, body.status, body.reason)

    @router.post('/projects/{project_id}/requirements')
    def intake(project_id: str, body: IntakeInput):
        return call(product.requirements.intake, web_actor, project_id, body.text,
                    body.request_id, body.task_id, body.title)

    @router.post('/projects/{project_id}/tasks/{task_id}/requirements/{requirement_id}/archive')
    def archive(project_id: str, task_id: str, requirement_id: str,
                body: ArchiveInput):
        return call(product.requirements.archive_by_human, web_actor, project_id,
                    task_id, requirement_id, body.expected_version, body.summary)

    @router.post('/projects/{project_id}/tasks/{task_id}/requirements/{requirement_id}/reopen')
    def reopen_requirement(project_id: str, task_id: str, requirement_id: str,
                           body: VersionedInput):
        return call(product.requirements.reopen_by_human, web_actor, project_id,
                    task_id, requirement_id, body.expected_version, body.reason)

    @router.post('/projects/{project_id}/proposals/{proposal_id}/review')
    def review(project_id: str, proposal_id: str, body: ReviewInput):
        return call(product.knowledge.review_contract, web_actor, project_id,
                    proposal_id, body.approve, body.reason)

    @router.get('/projects/{project_id}/topics')
    def list_topics(project_id: str, query: str = '', include_deleted: bool = False,
                    cursor: str | None = None, limit: int = Query(50, ge=1, le=100)):
        return call(product.topics.list_topics, web_actor, project_id, query, include_deleted, cursor, limit)

    @router.post('/projects/{project_id}/topics')
    def create_topic(project_id: str, body: TopicInput):
        return call(product.topics.create_topic, web_actor, body.key, body.name, body.description,
                    body.reason, project_id=project_id)

    @router.post('/projects/{project_id}/topics/enable')
    def enable_topics(project_id: str, body: StatusInput):
        return call(product.topics.enable_query, web_actor, project_id, body.expected_revision, body.reason)

    @router.get('/projects/{project_id}/topics/{key}')
    def get_topic(project_id: str, key: str, include_usage: bool = False):
        return call(product.topics.get_topic, web_actor, project_id, key, include_usage)

    @router.patch('/projects/{project_id}/topics/{key}')
    def update_topic(project_id: str, key: str, body: TopicUpdateInput):
        return call(product.topics.update_topic, web_actor, key, body.expected_version, body.reason,
                    body.name, body.description, project_id=project_id)

    @router.delete('/projects/{project_id}/topics/{key}')
    def delete_topic(project_id: str, key: str, body: VersionedInput):
        return call(product.topics.delete_topic, web_actor, key, body.expected_version,
                    body.reason, project_id=project_id)

    @router.post('/projects/{project_id}/rules/{rule_id}/review')
    def review_rule(project_id: str, rule_id: str, body: RuleReviewInput):
        return call(product.governance.review_task_rule, web_actor, project_id, rule_id,
                    body.expected_version, body.approve, body.reason)

    @router.post('/projects/{project_id}/rules/{rule_id}/classify')
    def classify_legacy_rule(project_id: str, rule_id: str, body: ClassifyInput):
        return call(product.knowledge.classify_legacy_rule, web_actor, project_id, rule_id,
                    body.expected_version, tuple(body.topics), body.reason,
                    tuple(body.patterns) if body.patterns is not None else None,
                    body.priority, body.is_global, body.priority_reason)

    @router.patch('/projects/{project_id}/findings/{finding_id}')
    def update_finding(project_id: str, finding_id: str, body: FindingUpdateInput):
        return call(product.context.update_finding, web_actor, finding_id, body.expected_version,
                    body.reason, tuple(body.topics) if body.topics is not None else None,
                    body.resolve, project_id=project_id)

    @router.get('/projects/{project_id}/ledger')
    def ledger(project_id: str):
        return call(product.ledger.project, web_actor, project_id)

    @router.get('/projects/{project_id}/tree')
    def tree(project_id: str, worktree_id: str | None = None):
        return call(product.ledger.scope_tree, web_actor, project_id, worktree_id)

    @router.get('/projects/{project_id}/inspect')
    def inspect(project_id: str, path: str, priorities: list[Priority] = Query(...), task_id: str | None = None):
        return call(product.ledger.inspect_path, web_actor, project_id, path, tuple(priorities), task_id)

    @router.get('/projects/{project_id}/events')
    def events(project_id: str, limit: int = Query(100, ge=1, le=100),
               before: int | None = Query(None, ge=1)):
        return call(product.ledger.events, web_actor, project_id, limit, before)

    return router
