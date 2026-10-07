"""FastAPI application providing REST endpoints, WebUI serving, and orchestration."""

import os
import uuid
import sqlite3
from functools import wraps
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from codeneuro.database import DomainError, Conflict
from codeneuro.service import ContextService
from codeneuro.migrations import SCHEMA_VERSION
from codeneuro.decomposer import Decomposer
from codeneuro.exporter import RuleExporter
from codeneuro.matcher import ScopeMatcher
from codeneuro.models import (
    AgentIssue,
    ContextResolution,
    Finding,
    FindingStatus,
    HealthCheckReport,
    IssueStatus,
    IssueType,
    Lifecycle,
    Priority,
    Project,
    Proposal,
    Rule,
    RuleEvaluation,
    RuleStatus,
    RuleVersion,
    Task,
    TaskStatus,
    WorktreeInstance,
)
from codeneuro.storage import Storage
from codeneuro.synthesizer import ContextSynthesizer


class CreateProjectReq(BaseModel):
    name: str
    description: Optional[str] = ""
    root_paths: Optional[List[str]] = None


class CreateTaskReq(BaseModel):
    id: Optional[str] = None
    title: str
    description: Optional[str] = ""
    status: TaskStatus = TaskStatus.ACTIVE


class CreateRuleReq(BaseModel):
    task_id: Optional[str] = None
    scope_patterns: List[str]
    priority: Priority = Priority.P1
    lifecycle: Lifecycle = Lifecycle.SHORT_TERM
    title: str
    content_points: List[str]
    created_by: str = "user"
    status: RuleStatus = RuleStatus.ACTIVE


class UpdateRuleReq(BaseModel):
    title: str
    content_points: List[str]
    scope_patterns: List[str]
    priority: Priority
    change_summary: str = "在线更新"
    operator: str = "user"
    expected_version: int = Field(ge=1)


class DecomposeReq(BaseModel):
    task_id: str
    text: str = Field(min_length=1, max_length=100000)
    known_paths: Optional[List[str]] = None


class CrystallizeFindingReq(BaseModel):
    title: str
    priority: Priority = Priority.P1
    lifecycle: Lifecycle = Lifecycle.LONG_TERM
    scope_patterns: Optional[List[str]] = None


class ExportReq(BaseModel):
    format: str = "cursor" # cursor | claude
    out_dir: Optional[str] = None
    task_id: Optional[str] = None


class WorktreeHeartbeatReq(BaseModel):
    id: str
    project_id: str
    machine_name: str = "local"
    worktree_path: str
    git_branch: str = "main"
    git_commit: Optional[str] = None
    active_task_id: Optional[str] = None
    current_file: Optional[str] = None
    agent_client: str = "Cursor"


class BindTaskReq(BaseModel):
    task_id: Optional[str] = None


class StartSessionReq(BaseModel):
    project_id: str
    workspace_path: str
    task_id: Optional[str] = None
    agent_client: str = "HTTP client"
    debug: bool = False


class DeliveryReq(BaseModel):
    session_id: str
    file_path: str
    request_id: Optional[str] = None
    max_chars: int = Field(default=24000, ge=512, le=200000)


class FeedbackReq(BaseModel):
    session_id: str
    delivery_id: str
    rule_id: str
    score: int = Field(ge=0, le=5)
    reason: str = ""


class AgentFindingReq(BaseModel):
    session_id: str
    target_path: str
    text: str
    priority: str = "P1"


def create_app(storage: Optional[Storage] = None, db_path: Optional[str] = None) -> FastAPI:
    owns_storage = storage is None
    if storage is None:
        actual_path = db_path or os.getenv("CODENEURO_DB", os.getenv("CODETOKEN_DB", "codeneuro.db"))
        storage = Storage(actual_path)

    @asynccontextmanager
    async def lifespan(app):
        yield
        if owns_storage:
            storage.close()
    app = FastAPI(title="CodeNeuro", version="0.4.0", lifespan=lifespan)
    service = ContextService(storage)
    app.state.storage = storage
    app.state.context_service = service

    @app.exception_handler(DomainError)
    async def domain_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"error": exc.code, "detail": str(exc)})

    @app.exception_handler(ValidationError)
    async def model_validation_error(request, exc):
        return JSONResponse(status_code=422, content={"error": "validation_error", "detail": exc.errors(include_input=False, include_context=False)})

    @app.exception_handler(sqlite3.IntegrityError)
    async def integrity_error(request, exc):
        return JSONResponse(status_code=409, content={"error": "integrity_conflict", "detail": "Duplicate identity or invalid referenced resource."})

    @app.middleware("http")
    async def browser_origin_guard(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != request.headers.get('host'):
                return JSONResponse(status_code=403, content={"detail": "Cross-origin writes are not allowed."})
        token = os.getenv('CODENEURO_API_TOKEN')
        if token and request.url.path.startswith('/api/'):
            import hmac
            supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
            if not hmac.compare_digest(supplied, token):
                return JSONResponse(status_code=401, content={"detail": "API token required."})
        return await call_next(request)

    def unit_of_work(*, write=False):
        def decorate(fn):
            @wraps(fn)
            def call(*args, **kwargs):
                with storage.transaction(write=write):
                    return fn(*args, **kwargs)
            return call
        return decorate


    matcher = ScopeMatcher()
    decomposer = Decomposer()
    static_dir = Path(__file__).parent / "static"

    # --- System Stats Endpoint ---

    @app.get("/api/stats")
    @unit_of_work(write=False)
    def get_global_stats():
        projects = storage.list_projects()
        all_rules = []
        for p in projects:
            all_rules.extend(storage.list_rules(p.id, status=None))

        p0 = sum(1 for r in all_rules if r.priority == Priority.P0 and r.status == RuleStatus.ACTIVE)
        p1 = sum(1 for r in all_rules if r.priority == Priority.P1 and r.status == RuleStatus.ACTIVE)
        p2 = sum(1 for r in all_rules if r.priority == Priority.P2 and r.status == RuleStatus.ACTIVE)
        total_hits = sum(r.hit_count for r in all_rules)
        long_term = sum(1 for r in all_rules if r.lifecycle == Lifecycle.LONG_TERM and r.status == RuleStatus.ACTIVE)
        short_term = sum(1 for r in all_rules if r.lifecycle == Lifecycle.SHORT_TERM and r.status == RuleStatus.ACTIVE)

        cur = storage.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM tasks WHERE status = 'active'")
        active_tasks = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM findings WHERE status = 'pending_review' AND source != 'demo'")
        pending_findings = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM proposals WHERE status = 'pending'")
        pending_proposals = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM agent_issues WHERE status = 'open' AND source != 'demo'")
        open_issues = cur.fetchone()[0]

        return {
            "total_projects": len(projects),
            "total_rules": len(all_rules),
            "active_rules": len([r for r in all_rules if r.status == RuleStatus.ACTIVE]),
            "p0_count": p0,
            "p1_count": p1,
            "p2_count": p2,
            "long_term_count": long_term,
            "short_term_count": short_term,
            "total_hits": total_hits,
            "active_tasks": active_tasks,
            "pending_findings": pending_findings,
            "pending_proposals": pending_proposals,
            "open_issues_count": open_issues,
        }

    # --- Project Endpoints ---

    @app.post("/api/projects", response_model=Project)
    @unit_of_work(write=True)
    def create_project(req: CreateProjectReq):
        pid = f"proj_{uuid.uuid4().hex}"
        p = Project(
            id=pid,
            name=req.name,
            description=req.description,
            root_paths=req.root_paths or ["."],
        )
        return storage.create_project(p)

    @app.get("/api/projects", response_model=List[Project])
    @unit_of_work(write=False)
    def list_projects():
        return storage.list_projects()

    @app.get("/api/projects/{project_id}", response_model=Project)
    @unit_of_work(write=False)
    def get_project(project_id: str):
        p = storage.get_project(project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Project not found")
        return p

    # --- Health Check & Conflict Detection Endpoint ---

    @app.get("/api/projects/{project_id}/health-check", response_model=HealthCheckReport)
    @unit_of_work(write=False)
    def check_health(project_id: str):
        get_project(project_id)
        return storage.check_project_health(project_id)

    # --- Task Endpoints ---

    @app.post("/api/projects/{project_id}/tasks", response_model=Task)
    @unit_of_work(write=True)
    def create_task(project_id: str, req: CreateTaskReq):
        get_project(project_id)
        tid = req.id or f"TASK-{uuid.uuid4().hex.upper()}"
        t = Task(
            id=tid,
            project_id=project_id,
            title=req.title,
            description=req.description,
            status=req.status,
        )
        return storage.create_task(t)

    @app.get("/api/projects/{project_id}/tasks", response_model=List[Task])
    @unit_of_work(write=False)
    def list_tasks(project_id: str):
        return storage.list_tasks(project_id)

    @app.patch("/api/tasks/{task_id}/status")
    @unit_of_work(write=True)
    def update_task_status(task_id: str, status: TaskStatus):
        success = storage.update_task_status(task_id, status)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "ok", "task_id": task_id, "new_status": status.value}

    # --- Rule Endpoints & Version History ---

    @app.post("/api/projects/{project_id}/rules", response_model=Rule)
    @unit_of_work(write=True)
    def create_rule(project_id: str, req: CreateRuleReq):
        get_project(project_id)
        rid = f"rule_{uuid.uuid4().hex}"
        r = Rule(
            id=rid,
            project_id=project_id,
            task_id=req.task_id,
            scope_patterns=req.scope_patterns,
            priority=req.priority,
            lifecycle=req.lifecycle,
            title=req.title,
            content_points=req.content_points,
            created_by=req.created_by,
            status=req.status,
        )
        saved = storage.create_rule(r)
        storage.log_telemetry_event(
            project_id=project_id,
            event_type="rule_edit",
            summary=f"创建新规约: {r.title} ({r.priority.value})",
            details={"rule_id": r.id, "priority": r.priority.value, "scopes": r.scope_patterns}
        )
        return saved

    @app.get("/api/projects/{project_id}/rules", response_model=List[Rule])
    @unit_of_work(write=False)
    def list_rules(
        project_id: str,
        task_id: Optional[str] = None,
        lifecycle: Optional[Lifecycle] = None,
        status: Optional[RuleStatus] = RuleStatus.ACTIVE,
    ):
        return storage.list_rules(
            project_id=project_id,
            task_id=task_id,
            lifecycle=lifecycle,
            status=status,
        )

    @app.put("/api/rules/{rule_id}", response_model=Rule)
    @unit_of_work(write=True)
    def update_rule_content(rule_id: str, req: UpdateRuleReq):
        updated = storage.update_rule_content(
            rule_id=rule_id,
            title=req.title,
            content_points=req.content_points,
            scope_patterns=req.scope_patterns,
            priority=req.priority,
            change_summary=req.change_summary,
            operator=req.operator,
            expected_version=req.expected_version
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Rule not found")
        storage.log_telemetry_event(
            project_id=updated.project_id,
            event_type="rule_edit",
            summary=f"更新规约至 v{updated.version}: {updated.title}",
            details={"rule_id": updated.id, "version": updated.version, "summary": req.change_summary}
        )
        return updated

    @app.get("/api/rules/{rule_id}/versions", response_model=List[RuleVersion])
    @unit_of_work(write=False)
    def list_rule_versions(rule_id: str):
        return storage.list_rule_versions(rule_id)

    @app.post("/api/rules/{rule_id}/rollback", response_model=Rule)
    @unit_of_work(write=True)
    def rollback_rule(rule_id: str, version: int = Query(...), expected_version: int = Query(..., ge=1)):
        rolled = storage.rollback_rule_version(rule_id=rule_id, target_version=version, expected_version=expected_version)
        if not rolled:
            raise HTTPException(status_code=404, detail=f"Target version v{version} not found for rule {rule_id}")
        storage.log_telemetry_event(
            project_id=rolled.project_id,
            event_type="rule_edit",
            summary=f"规约回滚至历史版本 v{version}: {rolled.title}",
            details={"rule_id": rolled.id, "target_version": version}
        )
        return rolled

    @app.patch("/api/rules/{rule_id}/status")
    @unit_of_work(write=True)
    def update_rule_status(rule_id: str, status: RuleStatus, expected_version: int = Query(..., ge=1)):
        success = storage.update_rule_status(rule_id, status, expected_version)
        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": "ok", "rule_id": rule_id, "new_status": status.value}

    @app.delete("/api/rules/{rule_id}")
    @unit_of_work(write=True)
    def delete_rule(rule_id: str, expected_version: int = Query(..., ge=1)):
        if not storage.delete_rule(rule_id, expected_version):
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": "ok", "deleted_rule_id": rule_id, "disposition": "revoked_with_history_preserved"}

    # --- Worktree Fleet Management Endpoints ---

    @app.post("/api/worktrees/heartbeat", response_model=WorktreeInstance)
    @unit_of_work(write=True)
    def worktree_heartbeat(req: WorktreeHeartbeatReq):
        wt = WorktreeInstance(
            id=req.id,
            project_id=req.project_id,
            machine_name=req.machine_name,
            worktree_path=req.worktree_path,
            git_branch=req.git_branch,
            git_commit=req.git_commit,
            active_task_id=req.active_task_id,
            current_file=req.current_file,
            agent_client=req.agent_client,
        )
        saved = storage.register_worktree_heartbeat(wt)
        storage.log_telemetry_event(
            project_id=req.project_id,
            event_type="heartbeat",
            summary=f"工作区心跳: {req.machine_name}:{req.worktree_path} (分支: {req.git_branch})",
            details={"worktree_id": req.id, "task": req.active_task_id, "client": req.agent_client}
        )
        return saved

    @app.get("/api/projects/{project_id}/worktrees", response_model=List[WorktreeInstance])
    @unit_of_work(write=False)
    def list_worktrees(project_id: str):
        return storage.list_worktrees(project_id)

    @app.post("/api/worktrees/{worktree_id}/bind-task")
    @unit_of_work(write=True)
    def bind_worktree_task(worktree_id: str, req: BindTaskReq):
        success = storage.bind_worktree_task(worktree_id, req.task_id)
        if not success:
            raise HTTPException(status_code=404, detail="Worktree not found")
        return {"status": "ok", "worktree_id": worktree_id, "bound_task_id": req.task_id}

    # --- Telemetry & Live Stream ---

    @app.get("/api/projects/{project_id}/telemetry")
    @unit_of_work(write=False)
    def list_telemetry(project_id: str, limit: int = 50):
        return {"project_id": project_id, "events": storage.list_telemetry_events(project_id, limit=limit)}

    # --- Context Resolution ---

    @app.get("/api/context", response_model=ContextResolution)
    @unit_of_work(write=False)
    def resolve_context(project_id: str, file_path: str, task_id: Optional[str] = None, debug: bool = False):
        # A WebUI probe is a read-only preview; only session delivery counts as use.
        return service.resolve(project_id=project_id, file_path=file_path, task_id=task_id, debug=debug)

    # --- Decompose Ingestion ---

    @app.post("/api/projects/{project_id}/decompose", response_model=List[Rule])
    @unit_of_work(write=True)
    def decompose_requirement(project_id: str, req: DecomposeReq):
        get_project(project_id)

        # Auto-create task if not present
        if req.task_id and not storage.get_task(req.task_id):
            storage.create_task(
                Task(
                    id=req.task_id,
                    project_id=project_id,
                    title=f"需求迭代 {req.task_id}",
                    description="由 PRD/需求自动拆解生成",
                    status=TaskStatus.ACTIVE,
                )
            )

        generated_rules = decomposer.heuristic_decompose(
            project_id=project_id,
            task_id=req.task_id,
            text=req.text,
            known_paths=req.known_paths,
        )
        saved_rules = []
        for r in generated_rules:
            r.status = RuleStatus.DRAFT
            saved_rules.append(storage.create_rule(r))

        storage.log_telemetry_event(
            project_id=project_id,
            event_type="rule_edit",
            summary=f"PRD 自动拆解入库: 任务 {req.task_id} (生成 {len(saved_rules)} 条规则)",
            details={"task_id": req.task_id, "rule_count": len(saved_rules)}
        )
        return saved_rules

    # --- Cognitive Tree & Heatmap ---

    @app.get("/api/projects/{project_id}/tree")
    @unit_of_work(write=False)
    def get_project_cognitive_tree(project_id: str):
        proj = storage.get_project(project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)

        known_files = set()
        skipped = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.codex', '.hermes'}
        for root_path in proj.root_paths:
            root = Path(root_path).resolve()
            if not root.is_dir():
                continue
            for current, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in skipped and not d.startswith('.') and not (Path(current)/d).is_symlink())
                for name in sorted(files):
                    f = Path(current) / name
                    if name.startswith('.') or not f.resolve().is_relative_to(root):
                        continue
                    known_files.add(f.relative_to(root).as_posix())
                    if len(known_files) >= 10000:
                        break
                if len(known_files) >= 10000:
                    break

        tree_root: Dict[str, Any] = {
            "name": proj.name,
            "path": "",
            "type": "directory",
            "p0_count": 0,
            "p1_count": 0,
            "p2_count": 0,
            "total_rules": 0,
            "children": {}
        }

        for fpath in known_files:
            matched = [r for r in rules if matcher.matches_rule(r, fpath)]

            parts = fpath.split("/")
            curr = tree_root
            curr_path = ""
            for idx, part in enumerate(parts):
                curr_path = f"{curr_path}/{part}" if curr_path else part
                is_leaf = (idx == len(parts) - 1) and ("." in part or "*" not in part)
                node_type = "file" if is_leaf else "directory"

                if part not in curr["children"]:
                    curr["children"][part] = {
                        "name": part,
                        "path": curr_path,
                        "type": node_type,
                        "p0_count": 0,
                        "p1_count": 0,
                        "p2_count": 0,
                        "total_rules": 0,
                        "rules": [],
                        "children": {}
                    }
                node = curr["children"][part]

                for r in matched:
                    if r.id not in [x["id"] for x in node["rules"]]:
                        node["rules"].append({"id": r.id, "title": r.title, "priority": r.priority.value, "lifecycle": r.lifecycle.value})
                        node["total_rules"] += 1
                        if r.priority == Priority.P0: node["p0_count"] += 1
                        elif r.priority == Priority.P1: node["p1_count"] += 1
                        else: node["p2_count"] += 1

                curr = node

        def format_node(node: Dict[str, Any]) -> Dict[str, Any]:
            children_list = [format_node(c) for c in node["children"].values()]
            children_list.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"].lower()))
            return {
                "name": node["name"],
                "path": node["path"],
                "type": node["type"],
                "p0_count": node["p0_count"],
                "p1_count": node["p1_count"],
                "p2_count": node["p2_count"],
                "total_rules": node["total_rules"],
                "rules": node.get("rules", []),
                "children": children_list
            }

        return {"project_id": project_id, "tree": format_node(tree_root)}

    @app.get("/api/projects/{project_id}/heatmap")
    @unit_of_work(write=False)
    def get_project_heatmap(project_id: str):
        rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        path_stats: Dict[str, Dict[str, Any]] = {}

        for r in rules:
            for pattern in r.scope_patterns:
                if pattern not in path_stats:
                    path_stats[pattern] = {
                        "pattern": pattern,
                        "total_rules": 0,
                        "p0_count": 0,
                        "p1_count": 0,
                        "p2_count": 0,
                        "long_term": 0,
                        "short_term": 0,
                        "tasks": set(),
                        "rule_titles": []
                    }
                stat = path_stats[pattern]
                stat["total_rules"] += 1
                stat["rule_titles"].append(r.title)
                if r.priority == Priority.P0:
                    stat["p0_count"] += 1
                elif r.priority == Priority.P1:
                    stat["p1_count"] += 1
                else:
                    stat["p2_count"] += 1

                if r.lifecycle == Lifecycle.LONG_TERM:
                    stat["long_term"] += 1
                else:
                    stat["short_term"] += 1

                if r.task_id:
                    stat["tasks"].add(r.task_id)

        result = []
        for k, v in path_stats.items():
            v["tasks"] = list(v["tasks"])
            result.append(v)

        result.sort(key=lambda x: (x["p0_count"] * 10 + x["p1_count"] * 3 + x["total_rules"]), reverse=True)
        return {"project_id": project_id, "heatmap": result}

    # --- Findings & Proposals Management ---

    @app.post("/api/projects/{project_id}/findings", response_model=Finding)
    @unit_of_work(write=True)
    def create_finding(project_id: str, req: Finding):
        if req.project_id != project_id:
            raise DomainError("URL and payload project differ.")
        if req.source != "human" or req.session_id:
            raise DomainError("Use the agent session endpoints for agent-attributed records.")
        saved = storage.create_finding(req)
        storage.log_telemetry_event(
            project_id=project_id,
            event_type="finding",
            summary=f"Agent 记录排坑事实: `{req.target_path}` ({req.suggested_priority.value})",
            details={"finding_id": saved.id, "text": req.finding_text}
        )
        return saved

    @app.get("/api/projects/{project_id}/findings", response_model=List[Finding])
    @unit_of_work(write=False)
    def list_findings(project_id: str, status: Optional[FindingStatus] = None):
        return storage.list_findings(project_id, status)

    @app.post("/api/projects/{project_id}/proposals", response_model=Proposal)
    @unit_of_work(write=True)
    def create_proposal(project_id: str, req: Proposal):
        if req.project_id != project_id:
            raise DomainError("URL and payload project differ.")
        return storage.create_proposal(req)

    @app.post("/api/findings/{finding_id}/crystallize", response_model=Rule)
    @unit_of_work(write=True)
    def crystallize_finding(finding_id: str, req: CrystallizeFindingReq):
        cur = storage.conn.cursor()
        cur.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Finding not found")

        if row["source"] == "demo" or row["status"] == "discarded":
            raise Conflict("Demo/discarded findings cannot be promoted.")
        target_finding = Finding(
            id=row["id"],
            project_id=row["project_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            target_path=row["target_path"],
            finding_text=row["finding_text"],
            suggested_priority=Priority(row["suggested_priority"]),
            status=FindingStatus(row["status"]),
        )

        existing = storage.get_rule("rule_finding_" + finding_id)
        if existing:
            return existing
        scopes = req.scope_patterns or [target_finding.target_path]
        rule_id = "rule_finding_" + finding_id
        new_rule = Rule(
            id=rule_id,
            project_id=target_finding.project_id,
            task_id=target_finding.task_id if req.lifecycle == Lifecycle.SHORT_TERM else None,
            scope_patterns=scopes,
            priority=req.priority,
            lifecycle=req.lifecycle,
            title=req.title,
            content_points=[target_finding.finding_text],
            created_by="crystallized_from_agent",
            status=RuleStatus.ACTIVE,
        )
        saved = storage.create_rule(new_rule)
        storage.update_finding_status(finding_id, FindingStatus.CRYSTALLIZED)
        storage.log_telemetry_event(
            project_id=target_finding.project_id,
            event_type="rule_edit",
            summary=f"排坑事实结晶升华: {new_rule.title} (长期契约 P0)",
            details={"rule_id": saved.id, "origin_finding": finding_id}
        )
        return saved

    @app.get("/api/projects/{project_id}/proposals", response_model=List[Proposal])
    @unit_of_work(write=False)
    def list_proposals(project_id: str, status: Optional[str] = None):
        return storage.list_proposals(project_id, status)

    @app.post("/api/proposals/{proposal_id}/approve", response_model=Rule)
    @unit_of_work(write=True)
    def approve_proposal(proposal_id: str):
        cur = storage.conn.cursor()
        cur.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")

        rule_id = "rule_proposal_" + proposal_id
        existing = storage.get_rule(rule_id)
        if existing:
            return existing
        if row["status"] != "pending":
            raise Conflict("Only pending proposals can be approved.")
        new_rule = Rule(
            id=rule_id,
            project_id=row["project_id"],
            task_id=None,
            scope_patterns=[row["target_component"]],
            priority=Priority.P0,
            lifecycle=Lifecycle.LONG_TERM,
            title=f"契约规范: {row['target_component']}",
            content_points=[row["proposed_contract"], f"演进理由: {row['justification']}"],
            created_by="human_approved_proposal",
            status=RuleStatus.ACTIVE,
        )
        saved = storage.create_rule(new_rule)
        cur.execute("UPDATE proposals SET status = 'approved' WHERE id = ?", (proposal_id,))
        storage.log_telemetry_event(
            project_id=row["project_id"],
            event_type="rule_edit",
            summary=f"审批通过架构提案: {new_rule.title}",
            details={"proposal_id": proposal_id, "rule_id": saved.id}
        )
        return saved

    # --- Debug Mode Evaluation & Issue Endpoints ---

    @app.post("/api/projects/{project_id}/evaluations", response_model=RuleEvaluation)
    @unit_of_work(write=True)
    def record_evaluation(project_id: str, req: RuleEvaluation):
        if req.project_id != project_id or not req.session_id or not req.delivery_id:
            raise DomainError("Feedback requires matching project, session_id and delivery_id.")
        session = service._session(req.session_id)
        if session['project_id'] != project_id:
            raise DomainError("Session belongs to another project.")
        result = service.evaluate(session_id=req.session_id, delivery_id=req.delivery_id, rule_id=req.rule_id, score=req.score, reason=req.reason or '')
        return next(e for e in storage.list_evaluations(project_id) if e.id == result['evaluation_id'])

    @app.get("/api/projects/{project_id}/evaluations", response_model=List[RuleEvaluation])
    @unit_of_work(write=False)
    def list_evaluations(project_id: str, rule_id: Optional[str] = None, limit: int = 100):
        return storage.list_evaluations(project_id, rule_id=rule_id, limit=limit)

    @app.post("/api/projects/{project_id}/issues", response_model=AgentIssue)
    @unit_of_work(write=True)
    def record_issue(project_id: str, req: AgentIssue):
        if req.project_id != project_id:
            raise DomainError("URL and payload project differ.")
        if req.source != "human" or req.session_id:
            raise DomainError("Use the agent session endpoints for agent-attributed records.")
        get_project(project_id)
        saved = storage.record_issue(req)
        storage.log_telemetry_event(
            project_id=project_id,
            event_type="issue",
            summary=f"Agent 申报架构异常工单: {req.title} [{req.issue_type.value}]",
            details={"issue_id": saved.id, "type": req.issue_type.value, "path": req.file_path}
        )
        return saved

    @app.get("/api/projects/{project_id}/issues", response_model=List[AgentIssue])
    @unit_of_work(write=False)
    def list_issues(project_id: str, status: Optional[IssueStatus] = None):
        return storage.list_issues(project_id, status)

    @app.post("/api/issues/{issue_id}/resolve")
    @unit_of_work(write=True)
    def resolve_issue(issue_id: str, status: IssueStatus = IssueStatus.RESOLVED):
        success = storage.resolve_issue(issue_id, status)
        if not success:
            raise HTTPException(status_code=404, detail="Issue not found")
        return {"status": "ok", "issue_id": issue_id, "resolved_status": status.value}

    @app.get("/api/projects/{project_id}/rule-quality")
    @unit_of_work(write=False)
    def get_rule_quality_metrics(project_id: str):
        rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        evals = storage.list_evaluations(project_id=project_id, limit=500)
        issues = storage.list_issues(project_id=project_id, status=IssueStatus.OPEN)

        quality_report = []
        for r in rules:
            quality_report.append({
                "rule_id": r.id,
                "title": r.title,
                "priority": r.priority.value,
                "lifecycle": r.lifecycle.value,
                "scope_patterns": r.scope_patterns,
                "version": r.version,
                "hit_count": r.hit_count,
                "eval_count": r.eval_count,
                "avg_score": r.avg_score,
                "zero_score_count": r.zero_score_count,
                "one_score_count": r.one_score_count,
                "fatigue_alert": r.zero_score_count >= 2,
                "noise_alert": r.one_score_count >= 2,
            })

        quality_report.sort(
            key=lambda x: (x["eval_count"] > 0, x["avg_score"] if x["avg_score"] is not None else 0),
            reverse=True
        )

        return {
            "project_id": project_id,
            "total_evaluations": len(evals),
            "open_issues_count": len(issues),
            "rules_quality": quality_report,
            "recent_issues": issues[:10],
            "recent_evaluations": evals[:20],
        }

    @app.get("/api/health")
    @unit_of_work(write=False)
    def readiness():
        storage.conn.execute("SELECT 1").fetchone()
        return {"status": "ok", "version": "0.4.0", "schema_version": SCHEMA_VERSION,
                "verified_deliveries": storage.conn.execute("SELECT count(*) FROM context_deliveries").fetchone()[0]}

    @app.post("/api/agent/sessions")
    @unit_of_work(write=True)
    def start_agent_session(req: StartSessionReq):
        return service.start_session(**req.model_dump())

    @app.post("/api/agent/sessions/{session_id}/close")
    @unit_of_work(write=True)
    def close_agent_session(session_id: str):
        return service.close_session(session_id)

    @app.get("/api/projects/{project_id}/sessions")
    @unit_of_work(write=False)
    def list_agent_sessions(project_id: str):
        storage.validate_scope(project_id)
        return [dict(r) for r in storage.conn.execute("SELECT * FROM agent_sessions WHERE project_id=? ORDER BY created_at DESC LIMIT 100", (project_id,))]

    @app.post("/api/agent/context", response_model=ContextResolution)
    @unit_of_work(write=True)
    def deliver_context(req: DeliveryReq):
        return service.resolve(**req.model_dump())

    @app.post("/api/agent/feedback")
    @unit_of_work(write=True)
    def agent_feedback(req: FeedbackReq):
        return service.evaluate(**req.model_dump())

    @app.post("/api/agent/findings", response_model=Finding)
    @unit_of_work(write=True)
    def agent_finding(req: AgentFindingReq):
        return service.record_finding(**req.model_dump())

    @app.get("/api/projects/{project_id}/audit")
    @unit_of_work(write=False)
    def audit_events(project_id: str, after: int = 0, limit: int = Query(100, ge=1, le=500)):
        storage.validate_scope(project_id)
        return [dict(r) for r in storage.conn.execute("SELECT * FROM audit_events WHERE project_id=? AND sequence>? ORDER BY sequence LIMIT ?", (project_id, after, limit))]

    # --- Static Exporter API ---

    @app.post("/api/projects/{project_id}/export")
    @unit_of_work(write=True)
    def export_rules(project_id: str, req: ExportReq):
        proj = storage.get_project(project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

        if not proj.root_paths:
            raise DomainError("Register a project root before exporting files.")
        target_dir = service._workspace(proj, req.out_dir or proj.root_paths[0])
        if req.format.lower() not in ('cursor', 'claude'):
            raise DomainError("Unsupported export format.")
        rules = service.eligible_rules(project_id, req.task_id)

        if req.format.lower() == "cursor":
            paths = RuleExporter.export_cursor_rules(rules, out_dir=target_dir, active_task_id=req.task_id)
            return {
                "format": "cursor",
                "target_dir": str(target_dir / ".cursor/rules"),
                "files_count": len(paths),
                "files": [p.name for p in paths]
            }
        else:
            p = RuleExporter.export_claude_md(rules, out_file=target_dir / "CLAUDE.md", active_task_id=req.task_id)
            return {
                "format": "claude",
                "target_file": str(p),
                "rules_count": len(rules)
            }

    # --- WebUI Static Files ---

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    @unit_of_work(write=False)
    def serve_index():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return "<h1>CodeNeuro Hub is running. (WebUI index.html not found)</h1>"

    return app
