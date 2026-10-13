"""Web API; only parameter mapping, never business state transitions."""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ...modules.tasks import ProductError, TaskStatus
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

    @router.post('/projects/{project_id}/proposals/{proposal_id}/review')
    def review(project_id: str, proposal_id: str, body: ReviewInput):
        return call(product.knowledge.review_contract, web_actor, project_id,
                    proposal_id, body.approve, body.reason)

    @router.get('/projects/{project_id}/ledger')
    def ledger(project_id: str):
        return call(product.ledger.project, web_actor, project_id)

    @router.get('/projects/{project_id}/tree')
    def tree(project_id: str, worktree_id: str | None = None):
        return call(product.ledger.scope_tree, web_actor, project_id, worktree_id)

    @router.get('/projects/{project_id}/inspect')
    def inspect(project_id: str, path: str, task_id: str | None = None):
        return call(product.ledger.inspect_path, web_actor, project_id, path, task_id)

    @router.get('/projects/{project_id}/events')
    def events(project_id: str, limit: int = Query(100, ge=1, le=100),
               before: int | None = Query(None, ge=1)):
        return call(product.ledger.events, web_actor, project_id, limit, before)

    return router
