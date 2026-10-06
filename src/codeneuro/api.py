"""FastAPI application providing REST endpoints, WebUI serving, and orchestration."""

import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from codeneuro.decomposer import Decomposer
from codeneuro.matcher import ScopeMatcher
from codeneuro.models import (
    ContextResolution,
    Finding,
    FindingStatus,
    Lifecycle,
    Priority,
    Project,
    Proposal,
    Rule,
    RuleStatus,
    Task,
    TaskStatus,
)
from codeneuro.storage import Storage
from codeneuro.synthesizer import ContextSynthesizer


class CreateProjectReq(BaseModel):
    name: str
    description: Optional[str] = ""
    root_paths: Optional[List[str]] = None


class CreateTaskReq(BaseModel):
    title: str
    description: Optional[str] = ""


class CreateRuleReq(BaseModel):
    task_id: Optional[str] = None
    scope_patterns: List[str]
    priority: Priority = Priority.P1
    lifecycle: Lifecycle = Lifecycle.SHORT_TERM
    title: str
    content_points: List[str]
    created_by: str = "user"


class DecomposeReq(BaseModel):
    task_id: str
    text: str
    known_paths: Optional[List[str]] = None


class CrystallizeFindingReq(BaseModel):
    title: str
    priority: Priority = Priority.P1
    lifecycle: Lifecycle = Lifecycle.LONG_TERM
    scope_patterns: Optional[List[str]] = None


def create_app(storage: Optional[Storage] = None, db_path: Optional[str] = None) -> FastAPI:
    if storage is None:
        actual_path = db_path or os.getenv("CODETOKEN_DB", "codeneuro.db")
        storage = Storage(actual_path)

    app = FastAPI(title="CodeNeuro Cognitive Context Hub", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    matcher = ScopeMatcher()
    decomposer = Decomposer()
    static_dir = Path(__file__).parent / "static"

    # --- Project Endpoints ---

    @app.post("/api/projects", response_model=Project)
    def create_project(req: CreateProjectReq):
        pid = f"proj_{uuid.uuid4().hex[:6]}"
        p = Project(
            id=pid,
            name=req.name,
            description=req.description,
            root_paths=req.root_paths or ["."],
        )
        return storage.create_project(p)

    @app.get("/api/projects", response_model=List[Project])
    def list_projects():
        return storage.list_projects()

    @app.get("/api/projects/{project_id}", response_model=Project)
    def get_project(project_id: str):
        p = storage.get_project(project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Project not found")
        return p

    # --- Task Endpoints ---

    @app.post("/api/projects/{project_id}/tasks", response_model=Task)
    def create_task(project_id: str, req: CreateTaskReq):
        get_project(project_id)
        tid = f"TASK-{uuid.uuid4().hex[:6].upper()}"
        t = Task(
            id=tid,
            project_id=project_id,
            title=req.title,
            description=req.description,
            status=TaskStatus.ACTIVE,
        )
        return storage.create_task(t)

    @app.get("/api/projects/{project_id}/tasks", response_model=List[Task])
    def list_tasks(project_id: str):
        return storage.list_tasks(project_id)

    @app.patch("/api/tasks/{task_id}/status")
    def update_task_status(task_id: str, status: TaskStatus):
        success = storage.update_task_status(task_id, status)
        if not success:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"status": "ok", "task_id": task_id, "new_status": status.value}

    # --- Rule Endpoints ---

    @app.post("/api/projects/{project_id}/rules", response_model=Rule)
    def create_rule(project_id: str, req: CreateRuleReq):
        get_project(project_id)
        rid = f"rule_{uuid.uuid4().hex[:8]}"
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
            status=RuleStatus.ACTIVE,
        )
        return storage.create_rule(r)

    @app.get("/api/projects/{project_id}/rules", response_model=List[Rule])
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

    @app.patch("/api/rules/{rule_id}/status")
    def update_rule_status(rule_id: str, status: RuleStatus):
        success = storage.update_rule_status(rule_id, status)
        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")
        return {"status": "ok", "rule_id": rule_id, "new_status": status.value}

    # --- Context Resolution ---

    @app.get("/api/context", response_model=ContextResolution)
    def resolve_context(
        project_id: str,
        file_path: str,
        task_id: Optional[str] = None,
    ):
        all_rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        long_term, short_term = matcher.filter_rules(
            all_rules, file_path=file_path, active_task_id=task_id
        )

        all_findings = storage.list_findings(
            project_id=project_id, status=FindingStatus.PENDING_REVIEW
        )
        matched_findings = [
            f for f in all_findings if matcher.matches_pattern(f.target_path, file_path) or f.target_path == file_path
        ]

        # Update hit counts
        hit_ids = [r.id for r in (long_term + short_term)]
        storage.increment_rule_hits(hit_ids)

        return ContextSynthesizer.synthesize(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term,
            short_term_rules=short_term,
            findings=matched_findings,
        )

    # --- Decompose Ingestion ---

    @app.post("/api/projects/{project_id}/decompose", response_model=List[Rule])
    def decompose_requirement(project_id: str, req: DecomposeReq):
        get_project(project_id)

        # Auto-create task if it does not exist yet to satisfy foreign key
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
            saved_rules.append(storage.create_rule(r))
        return saved_rules

    # --- Heatmap / Hierarchy Tree ---

    @app.get("/api/projects/{project_id}/heatmap")
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
                    }
                stat = path_stats[pattern]
                stat["total_rules"] += 1
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

        # Convert sets to lists
        result = []
        for k, v in path_stats.items():
            v["tasks"] = list(v["tasks"])
            result.append(v)

        result.sort(key=lambda x: (x["p0_count"] * 10 + x["p1_count"] * 3 + x["total_rules"]), reverse=True)
        return {"project_id": project_id, "heatmap": result}

    # --- Findings & Proposals Management ---

    @app.get("/api/projects/{project_id}/findings", response_model=List[Finding])
    def list_findings(project_id: str, status: Optional[FindingStatus] = None):
        return storage.list_findings(project_id, status)

    @app.post("/api/findings/{finding_id}/crystallize", response_model=Rule)
    def crystallize_finding(finding_id: str, req: CrystallizeFindingReq):
        """Promote an in-flight finding into a formal rule (either long-term or task rule)."""
        findings = storage.list_findings(project_id="", status=None)
        target_finding = next((f for f in findings if f.id == finding_id), None)
        if not target_finding:
            # Look up via direct query
            cur = storage.conn.cursor()
            cur.execute("SELECT * FROM findings WHERE id = ?", (finding_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Finding not found")
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

        scopes = req.scope_patterns or [target_finding.target_path]
        rule_id = f"rule_crys_{uuid.uuid4().hex[:6]}"
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
        return saved

    @app.get("/api/projects/{project_id}/proposals", response_model=List[Proposal])
    def list_proposals(project_id: str, status: Optional[str] = None):
        return storage.list_proposals(project_id, status)

    @app.post("/api/proposals/{proposal_id}/approve", response_model=Rule)
    def approve_proposal(proposal_id: str):
        cur = storage.conn.cursor()
        cur.execute("SELECT * FROM proposals WHERE id = ?", (proposal_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Proposal not found")

        rule_id = f"rule_arch_{uuid.uuid4().hex[:6]}"
        new_rule = Rule(
            id=rule_id,
            project_id=row["project_id"],
            task_id=None, # Long term
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
        return saved

    # --- WebUI Static Files ---

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def serve_index():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return "<h1>CodeNeuro Hub is running. (WebUI index.html not found)</h1>"

    return app
