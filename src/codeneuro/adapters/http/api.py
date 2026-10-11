"""Authenticated Web API; only parameter mapping, never business state transitions."""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, Field

from ...modules.tasks import ProductError
from ...workflows.product import Product
from ..mcp.identity import Identities


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


def create_router(product: Product, identities: Identities):
    router = APIRouter(prefix='/api')

    def actor(request: Request):
        auth = request.headers.get('authorization', '')
        if auth[:7].lower() != 'bearer ':
            raise HTTPException(status_code=401, detail='Bearer credential required.')
        try:
            return identities.authenticate(auth[7:])
        except ToolError:
            raise HTTPException(status_code=401, detail='Invalid credential.') from None

    def call(method, *args, **kwargs):
        try:
            value = method(*args, **kwargs)
            return asdict(value) if hasattr(value, '__dataclass_fields__') else value
        except ProductError as error:
            status = {'conflict': 409, 'forbidden': 403, 'not_found': 404}.get(error.code, 400)
            raise HTTPException(status_code=status, detail={'code': error.code, 'message': str(error)}) from error

    @router.get('/projects')
    def projects(request: Request):
        return call(product.workspaces.list_projects, actor(request))

    @router.post('/projects')
    def register(body: ProjectInput, request: Request):
        return call(product.workspaces.register_project, actor(request), body.id, body.name)

    @router.get('/projects/{project_id}/tasks')
    def tasks(project_id: str, request: Request):
        return call(product.workspaces.list_tasks, actor(request), project_id)

    @router.post('/projects/{project_id}/tasks/{task_id}/pause')
    def pause(project_id: str, task_id: str, body: StatusInput, request: Request):
        return call(product.workspaces.pause_task, actor(request), project_id,
                    task_id, body.expected_revision, body.reason)

    @router.post('/projects/{project_id}/tasks/{task_id}/resume')
    def resume(project_id: str, task_id: str, body: StatusInput, request: Request):
        return call(product.workspaces.resume_task, actor(request), project_id,
                    task_id, body.expected_revision, body.reason)

    @router.post('/projects/{project_id}/requirements')
    def intake(project_id: str, body: IntakeInput, request: Request):
        return call(product.requirements.intake, actor(request), project_id, body.text,
                    body.request_id, body.task_id, body.title)

    @router.post('/projects/{project_id}/tasks/{task_id}/requirements/{requirement_id}/archive')
    def archive(project_id: str, task_id: str, requirement_id: str,
                body: ArchiveInput, request: Request):
        return call(product.requirements.archive_by_human, actor(request), project_id,
                    task_id, requirement_id, body.expected_version, body.summary)

    @router.post('/projects/{project_id}/proposals/{proposal_id}/review')
    def review(project_id: str, proposal_id: str, body: ReviewInput, request: Request):
        return call(product.knowledge.review_contract, actor(request), project_id,
                    proposal_id, body.approve, body.reason)

    @router.get('/projects/{project_id}/ledger')
    def ledger(project_id: str, request: Request):
        return call(product.ledger.project, actor(request), project_id)

    return router
