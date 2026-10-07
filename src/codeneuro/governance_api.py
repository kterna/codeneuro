"""HTTP DTOs for the governance domain. Hosts wire authentication/error handling."""
from typing import Literal
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field
from .governance import GovernanceService


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Reason(Input):
    reason: str = Field(min_length=1, max_length=30000)


class AgentRuleCreate(Reason):
    session_id: str
    title: str = Field(min_length=1, max_length=500)
    content_points: list[str]
    scope_patterns: list[str]
    priority: Literal['P0', 'P1', 'P2'] = 'P1'
    activate: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    half_life_days: float = Field(default=30, ge=1, le=3650)


class AgentRuleUpdate(Reason):
    session_id: str
    expected_version: int = Field(ge=1)
    action: Literal['update', 'activate', 'reduce_priority', 'revoke']
    title: str | None = None
    content_points: list[str] | None = None
    scope_patterns: list[str] | None = None
    priority: Literal['P0', 'P1', 'P2'] | None = None


class Observation(Reason):
    session_id: str
    expected_version: int = Field(ge=1)
    test_run_id: str
    supports: bool


class TestRun(Input):
    session_id: str
    request_id: str = Field(min_length=1, max_length=200)
    command: list[str]
    exit_code: int
    stdout: str = ''
    stderr: str = ''
    started_at: str
    finished_at: str
    paths: list[str]


class Reflection(Input):
    session_id: str
    analysis: str = Field(min_length=1, max_length=30000)


class Cleanup(Input):
    request_id: str = 'automatic-close'
    close: bool = True


class Preflight(Input):
    session_id: str
    request_id: str
    files: list[str]
    plan: str
    diff: str = ''


class Change(Input):
    action: Literal['create', 'update', 'merge', 'revoke']
    rule_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    title: str | None = None
    content_points: list[str] | None = None
    scope_patterns: list[str] | None = None
    priority: Literal['P0', 'P1', 'P2'] | None = None
    source_rule_ids: list[str] = Field(default_factory=list)


class SourceRef(Input):
    kind: Literal['rule', 'finding', 'issue', 'test_run']
    id: str
    version: int | None = None


class ProposalCreate(Reason):
    change: Change
    source_refs: list[SourceRef] = Field(default_factory=list)
    task_id: str | None = None


class Review(Reason):
    reviewed: bool
    reviewer: str = 'human'


class Reject(Reason):
    reviewer: str = 'human'


class IssueApply(Review):
    change: Change


class Policy(Input):
    expected_version: int = Field(ge=1)
    spec: dict
    reviewed: bool
    reviewer: str = 'human'


def create_governance_router(storage, context_service=None, intelligence=None):
    router = APIRouter()
    service = GovernanceService(storage, context_service, intelligence)

    @router.patch('/api/tasks/{task_id}/pause')
    def pause(task_id: str, req: Reason):
        return service.pause_task(task_id, req.reason)

    @router.patch('/api/tasks/{task_id}/resume')
    def resume(task_id: str, req: Reason):
        return service.resume_task(task_id, req.reason)

    @router.post('/api/agent/rules')
    def create_rule(req: AgentRuleCreate):
        return service.create_rule(**req.model_dump())

    @router.patch('/api/agent/rules/{rule_id}')
    def update_rule(rule_id: str, req: AgentRuleUpdate):
        return service.mutate_rule(rule_id=rule_id, **req.model_dump())

    @router.post('/api/agent/rules/{rule_id}/observations')
    def observe(rule_id: str, req: Observation):
        return service.observe_rule(rule_id=rule_id, **req.model_dump())

    @router.post('/api/agent/test-runs')
    def test_run(req: TestRun):
        return service.record_test_run(**req.model_dump())

    @router.post('/api/agent/reflections/{reflection_id}')
    def reflect(reflection_id: str, req: Reflection):
        return service.explain_reflection(reflection_id=reflection_id, **req.model_dump())

    @router.post('/api/agent/sessions/{session_id}/cleanup')
    def cleanup(session_id: str, req: Cleanup, background_tasks: BackgroundTasks):
        result = service.cleanup_session(session_id, **req.model_dump())
        background_tasks.add_task(service.process_pending_distillations)
        return result

    @router.post('/api/agent/preflight')
    def preflight(req: Preflight):
        return service.preflight(**req.model_dump())

    @router.get('/api/projects/{project_id}/governance')
    def overview(project_id: str):
        return service.overview(project_id)

    @router.post('/api/projects/{project_id}/governance/proposals')
    def propose(project_id: str, req: ProposalCreate):
        return service.propose_change(project_id, **req.model_dump(exclude_none=True))

    @router.post('/api/governance/proposals/{proposal_id}/apply')
    def apply(proposal_id: str, req: Review):
        return service.apply_proposal(proposal_id, **req.model_dump())

    @router.post('/api/governance/proposals/{proposal_id}/reject')
    def reject(proposal_id: str, req: Reject):
        return service.reject_proposal(proposal_id, **req.model_dump())

    @router.post('/api/issues/{issue_id}/apply-suggestion')
    def apply_issue(issue_id: str, req: IssueApply):
        return service.apply_issue_suggestion(issue_id, **req.model_dump(exclude_none=True))

    @router.post('/api/rules/{rule_id}/policy')
    def policy(rule_id: str, req: Policy):
        return service.set_policy(rule_id, **req.model_dump())

    return router
