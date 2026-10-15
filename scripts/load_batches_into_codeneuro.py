#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Load extracted batch results into CodeNeuro SQLite database with full domain invariants."""

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to sys.path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))

import sqlalchemy as sa
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.adapters.sqlite.schema import (
    CURRENT_SCHEMA, projects, tasks, requirements, requirement_versions,
    rules, rule_versions, worktrees, sessions, findings, audit,
    requirement_rule_links
)
from codeneuro.modules.knowledge import Priority, Rule, relative_path, validate_rule
from codeneuro.modules.governance import validate_plan
from codeneuro.modules.topics import Topic, validate_definition, validate_keys
from codeneuro.modules.tasks import Requirement, RequirementStatus, Task, TaskStatus
from codeneuro.modules.workspaces import Session, Worktree
from codeneuro.modules.findings import Finding

DEFAULT_ACTOR_ID = 'batch-importer'
DEFAULT_AGENT_CLIENT = 'batch-loader'


def validate_id(ident: str) -> bool:
    return isinstance(ident, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', ident))


def validate_project_id(pid: str) -> bool:
    return validate_id(pid)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def worktree_id_for(project_id: str, actor_id: str = DEFAULT_ACTOR_ID) -> str:
    """Deterministic, unambiguous namespaced worktree ID."""
    key = f"worktree\0{project_id}\0{actor_id}"
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    return f"wt_imp_{digest}"


def project_session_id_for(project_id: str, actor_id: str = DEFAULT_ACTOR_ID) -> str:
    """Deterministic, unambiguous namespaced project session ID."""
    key = f"session\0project\0{project_id}\0{actor_id}"
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    return f"sess_imp_{digest}"


def task_session_id_for(project_id: str, task_id: str, actor_id: str = DEFAULT_ACTOR_ID) -> str:
    """Deterministic, unambiguous namespaced task session ID."""
    key = f"session\0task\0{project_id}\0{task_id}\0{actor_id}"
    digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
    return f"sess_imp_{digest}"


class ValidatedBatches(list):
    def __init__(self, batches, projects_map, tasks_map, requirements_map, rules_map, findings_map, topics_map):
        super().__init__(batches)
        self.projects_map = projects_map
        self.tasks_map = tasks_map
        self.requirements_map = requirements_map
        self.rules_map = rules_map
        self.findings_map = findings_map
        self.topics_map = topics_map


class PreflightResult:
    def __init__(self):
        self.existing_projects: set[str] = set()
        self.existing_worktrees: set[str] = set()
        self.existing_sessions: set[str] = set()
        self.existing_tasks: set[str] = set()
        self.existing_requirements: set[str] = set()
        self.existing_rules: set[str] = set()
        self.existing_links: set[tuple[str, str]] = set()
        self.existing_findings: set[str] = set()


def load_and_validate(files: list[str]) -> ValidatedBatches:
    """Validate batch structures, domain invariants, and cross-file references."""
    known_projects: dict[str, dict] = {}
    known_tasks: dict[str, dict] = {}
    known_requirements: dict[str, dict] = {}
    known_rules: dict[str, dict] = {}
    known_findings: dict[str, dict] = {}
    known_topics: dict[tuple[str, str], Topic] = {}

    parsed_batches = []
    errors = []

    # 1. Parse JSON files and collect projects across all batches
    for f in files:
        file_path = str(f)
        try:
            with open(file_path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
        except Exception as exc:
            errors.append(f"{file_path}: failed to read JSON: {exc}")
            continue

        if not isinstance(data, dict):
            errors.append(f"{file_path}: root JSON value must be an object, got {type(data).__name__}")
            continue

        # Check collection shapes: null/numeric/object for collections must be rejected
        for key in ('projects', 'tasks', 'rules', 'findings', 'topics'):
            if key in data and not isinstance(data[key], list):
                errors.append(f"{file_path}: '{key}' must be a list, got {type(data[key]).__name__}")

        batch_projects = []
        raw_p_list = data.get('projects')
        p_list = raw_p_list if isinstance(raw_p_list, list) else []
        for idx, p in enumerate(p_list):
            if not isinstance(p, dict):
                errors.append(f"{file_path}: projects[{idx}] must be an object, got {type(p).__name__}")
                continue

            raw_pid = p.get('id')
            if raw_pid is None or not isinstance(raw_pid, str) or not raw_pid.strip():
                errors.append(f"{file_path}: projects[{idx}] missing or non-string 'id'")
                continue
            pid = raw_pid.strip()
            if not validate_project_id(pid):
                errors.append(f"{file_path}: projects[{idx}] invalid project ID '{pid}'")
                continue

            if 'name' in p:
                if not isinstance(p['name'], str) or not p['name'].strip():
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') 'name' must be a non-empty string")
                    pname = pid
                elif len(p['name'].strip()) > 500:
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') name exceeds 500 chars")
                    pname = p['name'].strip()
                else:
                    pname = p['name'].strip()
            else:
                pname = pid

            # Missing provenance honest defaults: unknown / not_attested
            if 'workspace' in p:
                if not isinstance(p['workspace'], str) or not p['workspace'].strip():
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') 'workspace' must be a non-empty string")
                    ws = 'unknown'
                else:
                    ws = p['workspace'].strip()
            else:
                ws = 'unknown'

            if 'git_branch' in p:
                if not isinstance(p['git_branch'], str) or not p['git_branch'].strip():
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') 'git_branch' must be a non-empty string")
                    branch = 'unknown'
                else:
                    branch = p['git_branch'].strip()
            else:
                branch = 'unknown'

            if 'machine_name' in p:
                if not isinstance(p['machine_name'], str) or not p['machine_name'].strip():
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') 'machine_name' must be a non-empty string")
                    machine = 'not_attested'
                else:
                    machine = p['machine_name'].strip()
            else:
                machine = 'not_attested'

            if 'platform' in p:
                if not isinstance(p['platform'], str) or p['platform'].strip().lower() not in ('windows', 'linux', 'macos', 'unknown'):
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') invalid platform '{p.get('platform')}'")
                    platform = 'unknown'
                else:
                    platform = p['platform'].strip().lower()
            else:
                platform = 'unknown'

            repo_identity = p.get('repo_identity')
            if repo_identity is not None:
                if not isinstance(repo_identity, str) or len(repo_identity) > 128:
                    errors.append(f"{file_path}: projects[{idx}] ('{pid}') invalid 'repo_identity'")
                    repo_identity = None
                else:
                    repo_identity = repo_identity.strip()

            p_def = {
                'id': pid,
                'name': pname,
                'workspace': ws,
                'branch': branch,
                'machine': machine,
                'platform': platform,
                'repo_identity': repo_identity,
                'file': file_path,
            }

            if pid in known_projects:
                prior = known_projects[pid]
                if (prior['name'] != pname or prior['workspace'] != ws or prior['branch'] != branch or
                        prior['machine'] != machine or prior['platform'] != platform or
                        prior['repo_identity'] != repo_identity):
                    errors.append(
                        f"{file_path}: projects[{idx}] ('{pid}') conflicting duplicate declaration with {prior['file']}"
                    )
            else:
                known_projects[pid] = p_def

            batch_projects.append(p_def)

        parsed_batches.append({
            'file': file_path,
            'data': data,
            'projects': batch_projects,
        })

    # Explicit topic declarations are independent of rules; no keys are inferred from knowledge.
    for batch in parsed_batches:
        declarations = batch['data'].get('topics', [])
        for item in declarations if isinstance(declarations, list) else []:
            try:
                if not isinstance(item, dict) or set(item) != {'project_id', 'key', 'name', 'description'}:
                    raise ValueError('Topic declarations require project_id, key, name and description.')
                if item['project_id'] not in known_projects:
                    raise ValueError('Topic references an unknown project_id.')
                validate_definition(item['key'], item['name'], item['description'])
                topic = Topic(**item)
                identity = (topic.project_id, topic.key)
                if identity in known_topics and known_topics[identity] != topic:
                    raise ValueError('Conflicting duplicate topic declaration.')
                known_topics[identity] = topic
            except (ValueError, TypeError, AttributeError) as error:
                errors.append(f"{batch['file']}: invalid topic: {error}")

    # 2. Collect and validate tasks and their nested requirements across all batches
    for batch in parsed_batches:
        file_path = batch['file']
        data = batch['data']

        raw_t_list = data.get('tasks')
        t_list = raw_t_list if isinstance(raw_t_list, list) else []
        for idx, t in enumerate(t_list):
            if not isinstance(t, dict):
                errors.append(f"{file_path}: tasks[{idx}] must be an object, got {type(t).__name__}")
                continue

            raw_tid = t.get('id')
            if raw_tid is None or not isinstance(raw_tid, str) or not raw_tid.strip():
                errors.append(f"{file_path}: tasks[{idx}] missing or non-string 'id'")
                continue
            tid = raw_tid.strip()
            if not validate_id(tid):
                errors.append(f"{file_path}: tasks[{idx}] invalid task ID '{tid}'")
                continue

            raw_pid = t.get('project_id')
            if raw_pid is None or not isinstance(raw_pid, str) or not raw_pid.strip():
                errors.append(f"{file_path}: tasks[{idx}] ('{tid}') missing or non-string 'project_id'")
                continue
            pid = raw_pid.strip()
            if pid not in known_projects:
                errors.append(f"{file_path}: tasks[{idx}] ('{tid}') references unknown project_id '{pid}'")
                continue

            raw_title = t.get('title')
            if raw_title is None or not isinstance(raw_title, str) or not raw_title.strip():
                errors.append(f"{file_path}: tasks[{idx}] ('{tid}') missing or empty 'title'")
                ttitle = ''
            elif len(raw_title.strip()) > 500:
                errors.append(f"{file_path}: tasks[{idx}] ('{tid}') title exceeds 500 chars")
                ttitle = raw_title.strip()
            else:
                ttitle = raw_title.strip()

            raw_desc = t.get('description', '')
            if not isinstance(raw_desc, str):
                errors.append(f"{file_path}: tasks[{idx}] ('{tid}') 'description' must be a string")
                tdesc = ''
            else:
                tdesc = raw_desc

            # Status default: absent defaults to 'active'; explicit invalid/null/empty must fail
            if 'status' in t:
                raw_stat = t['status']
                if not isinstance(raw_stat, str) or raw_stat.strip().lower() not in (
                    'draft', 'active', 'testing', 'paused', 'released', 'archived'
                ):
                    errors.append(
                        f"{file_path}: tasks[{idx}] ('{tid}') invalid or empty status '{t.get('status')}'"
                    )
                    raw_status = 'active'
                else:
                    raw_status = raw_stat.strip().lower()
            else:
                raw_status = 'active'

            # Paused task state invariant
            if 'paused_from' in t:
                raw_pf = t['paused_from']
                if raw_status == 'paused':
                    if not isinstance(raw_pf, str) or raw_pf.strip().lower() not in ('active', 'testing'):
                        errors.append(
                            f"{file_path}: tasks[{idx}] ('{tid}') paused task requires paused_from in ('active', 'testing'), got '{raw_pf}'"
                        )
                        paused_from = None
                    else:
                        paused_from = raw_pf.strip().lower()
                else:
                    if raw_pf is not None:
                        errors.append(
                            f"{file_path}: tasks[{idx}] ('{tid}') non-paused task cannot specify paused_from"
                        )
                    paused_from = None
            else:
                if raw_status == 'paused':
                    errors.append(
                        f"{file_path}: tasks[{idx}] ('{tid}') paused task requires paused_from in ('active', 'testing')"
                    )
                paused_from = None

            # Requirements validation
            if 'requirements' in t:
                raw_reqs = t['requirements']
                if not isinstance(raw_reqs, list):
                    errors.append(f"{file_path}: tasks[{idx}] ('{tid}') 'requirements' must be a list, got {type(raw_reqs).__name__}")
                    req_list = []
                else:
                    req_list = raw_reqs
            else:
                req_list = []

            # Invariant: archived / released task cannot have active requirements
            if raw_status in ('released', 'archived'):
                for r_idx, req in enumerate(req_list):
                    if isinstance(req, dict):
                        r_stat = req.get('status')
                        if r_stat is None or (isinstance(r_stat, str) and r_stat.strip().lower() == 'active'):
                            errors.append(
                                f"{file_path}: tasks[{idx}] ('{tid}') is {raw_status} but requirements[{r_idx}] has active status; archived/released tasks cannot have active requirements"
                            )

            task_req_ids = []
            for r_idx, req in enumerate(req_list):
                if not isinstance(req, dict):
                    errors.append(f"{file_path}: tasks[{idx}] ('{tid}') requirements[{r_idx}] must be an object, got {type(req).__name__}")
                    continue

                if 'id' in req:
                    raw_rid = req['id']
                    if not isinstance(raw_rid, str) or not validate_id(raw_rid.strip()):
                        errors.append(f"{file_path}: tasks[{idx}] ('{tid}') requirements[{r_idx}] invalid ID '{raw_rid}'")
                        rid = f"req_{tid}_{r_idx+1}"
                    else:
                        rid = raw_rid.strip()
                else:
                    rid = f"req_{tid}_{r_idx+1}"

                # Text: preserve exact content; reject non-string / empty
                raw_text = req.get('text') if req.get('text') is not None else req.get('original_text')
                if raw_text is None or not isinstance(raw_text, str) or not raw_text.strip():
                    errors.append(f"{file_path}: tasks[{idx}] ('{tid}') requirements[{r_idx}] ('{rid}') missing or empty text")
                    r_text = ''
                else:
                    r_text = raw_text

                # Status default: absent defaults to 'active'; explicit invalid must fail
                if 'status' in req:
                    raw_rstat = req['status']
                    if not isinstance(raw_rstat, str) or raw_rstat.strip().lower() not in ('active', 'archived'):
                        errors.append(
                            f"{file_path}: tasks[{idx}] ('{tid}') requirements[{r_idx}] ('{rid}') invalid status '{raw_rstat}'"
                        )
                        r_status = 'active'
                    else:
                        r_status = raw_rstat.strip().lower()
                else:
                    r_status = 'active'

                raw_summary = req.get('summary') if req.get('summary') is not None else req.get('completion_summary')
                if raw_summary is not None:
                    if not isinstance(raw_summary, str):
                        errors.append(f"{file_path}: tasks[{idx}] requirement '{rid}' summary must be a string")
                        r_summary = None
                    else:
                        r_summary = raw_summary
                else:
                    r_summary = None

                # Invariant: archived requirement requires non-empty summary
                if r_status == 'archived':
                    if not r_summary or not r_summary.strip():
                        errors.append(
                            f"{file_path}: tasks[{idx}] requirement '{rid}' is archived and requires a non-empty completion summary"
                        )

                req_def = {
                    'id': rid,
                    'project_id': pid,
                    'task_id': tid,
                    'text': r_text,
                    'status': r_status,
                    'summary': r_summary,
                    'file': file_path,
                }

                if rid in known_requirements:
                    prior_req = known_requirements[rid]
                    if (prior_req['project_id'] != pid or prior_req['task_id'] != tid or
                            prior_req['text'] != r_text or prior_req['status'] != r_status or
                            prior_req['summary'] != r_summary):
                        errors.append(
                            f"{file_path}: tasks[{idx}] requirement '{rid}' conflicting duplicate declaration with {prior_req['file']}"
                        )
                else:
                    known_requirements[rid] = req_def

                task_req_ids.append(rid)

            if tid in known_tasks:
                prior = known_tasks[tid]
                if prior['project_id'] != pid:
                    errors.append(
                        f"{file_path}: tasks[{idx}] ('{tid}') cross-project duplicate ID: declared for '{pid}' but already assigned to '{prior['project_id']}' in {prior['file']}"
                    )
                elif (prior['title'] != ttitle or prior['description'] != tdesc or
                        prior['status'] != raw_status or prior['paused_from'] != paused_from or
                        prior['requirement_ids'] != task_req_ids):
                    errors.append(
                        f"{file_path}: tasks[{idx}] ('{tid}') conflicting duplicate declaration with {prior['file']}"
                    )
            else:
                known_tasks[tid] = {
                    'id': tid,
                    'project_id': pid,
                    'title': ttitle,
                    'description': tdesc,
                    'status': raw_status,
                    'paused_from': paused_from,
                    'requirement_ids': task_req_ids,
                    'file': file_path,
                }

    # 3. Validate rules across all batches
    for b_idx, batch in enumerate(parsed_batches):
        file_path = batch['file']
        data = batch['data']

        raw_r_list = data.get('rules')
        r_list = raw_r_list if isinstance(raw_r_list, list) else []
        for idx, r in enumerate(r_list):
            if not isinstance(r, dict):
                errors.append(f"{file_path}: rules[{idx}] must be an object, got {type(r).__name__}")
                continue

            if 'id' in r:
                raw_rid = r['id']
                if not isinstance(raw_rid, str) or not validate_id(raw_rid.strip()):
                    errors.append(f"{file_path}: rules[{idx}] invalid rule ID '{raw_rid}'")
                    rid = f"rule_{b_idx+1}_{idx+1}"
                else:
                    rid = raw_rid.strip()
            else:
                rid = f"rule_{b_idx+1}_{idx+1}"

            raw_rtitle = r.get('title')
            if raw_rtitle is None or not isinstance(raw_rtitle, str) or not raw_rtitle.strip():
                errors.append(f"{file_path}: rules[{idx}] missing or empty 'title'")
                rtitle = ''
            elif len(raw_rtitle.strip()) > 500:
                errors.append(f"{file_path}: rules[{idx}] title exceeds 500 chars")
                rtitle = raw_rtitle.strip()
            else:
                rtitle = raw_rtitle.strip()

            raw_pid = r.get('project_id')
            if raw_pid is None or not isinstance(raw_pid, str) or not raw_pid.strip():
                errors.append(f"{file_path}: rules[{idx}] missing or non-string 'project_id'")
                pid = ''
            else:
                pid = raw_pid.strip()
                if pid not in known_projects:
                    errors.append(f"{file_path}: rules[{idx}] ('{rtitle[:30]}') references unknown project_id '{pid}'")

            tid = r.get('task_id')
            if tid is not None:
                if not isinstance(tid, str) or not tid.strip():
                    errors.append(f"{file_path}: rules[{idx}] ('{rid}') 'task_id' must be a non-empty string when provided")
                    tid = None
                else:
                    tid = tid.strip()
                    if tid not in known_tasks:
                        errors.append(f"{file_path}: rules[{idx}] references unknown task_id '{tid}' in project '{pid}'")
                    elif known_tasks[tid]['project_id'] != pid:
                        errors.append(
                            f"{file_path}: rules[{idx}] task_id '{tid}' belongs to project '{known_tasks[tid]['project_id']}', not '{pid}'"
                        )
            else:
                tid = None

            # Points validation: required real input
            if 'points' not in r or not isinstance(r['points'], list) or len(r['points']) == 0:
                errors.append(f"{file_path}: rules[{idx}] ('{rid}') 'points' is required and must be a non-empty list of strings")
                points = []
            else:
                points = []
                for pt_idx, pt in enumerate(r['points']):
                    if not isinstance(pt, str) or not pt.strip():
                        errors.append(f"{file_path}: rules[{idx}] ('{rid}') points[{pt_idx}] must be a non-empty string")
                    else:
                        points.append(pt.strip())

            # Patterns validation: required real input (do not invent global **)
            if 'patterns' not in r or not isinstance(r['patterns'], list):
                errors.append(f"{file_path}: rules[{idx}] ('{rid}') 'patterns' is required and must be a list of real path patterns (possibly empty)")
                patterns = []
            else:
                patterns = []
                for pat_idx, pat in enumerate(r['patterns']):
                    if not isinstance(pat, str) or not pat.strip():
                        errors.append(f"{file_path}: rules[{idx}] ('{rid}') patterns[{pat_idx}] must be a non-empty string")
                    else:
                        clean_pat = pat.strip()
                        try:
                            relative_path(clean_pat, pattern=True)
                            patterns.append(clean_pat)
                        except Exception as pe:
                            errors.append(f"{file_path}: rules[{idx}] ('{rid}') patterns[{pat_idx}] '{pat}' invalid domain pattern: {pe}")

            # Explicit v2 classification; old categories are not converted into business topics.
            if 'priority' in r:
                raw_p = r['priority']
                if not isinstance(raw_p, str) or raw_p.strip().upper() not in ('P0', 'P1', 'P2', 'P3'):
                    errors.append(
                        f"{file_path}: rules[{idx}] ('{rid}') invalid priority '{raw_p}', must be P0, P1, P2, or P3"
                    )
                    priority = 'P1'
                else:
                    priority = raw_p.strip().upper()
            else:
                priority = 'P1'

            if 'category' in r:
                errors.append(f"{file_path}: rules[{idx}] obsolete category; supply registered topics and a validation_spec")
            topic_keys = r.get('topics', [])
            if not isinstance(topic_keys, list) or any(not isinstance(key, str) for key in topic_keys):
                errors.append(f"{file_path}: rules[{idx}] topics must be a list of registered keys")
                topic_keys = []
            topic_keys = tuple(sorted(topic_keys))
            is_global = r.get('is_global', False)
            priority_reason = r.get('priority_reason', '')
            validation_spec = r.get('validation_spec')
            try:
                validate_plan(validation_spec, len(points))
                if validation_spec['kind'] != 'review':
                    raise ValueError('Batch ingestion does not fabricate test validation; use the candidate evidence workflow.')
                validate_rule(Rule(rid, pid, tid, rtitle, tuple(points), tuple(patterns), Priority(priority),
                                  topic_keys, 1, 'draft', is_global=is_global,
                                  priority_reason=priority_reason, validation_spec=validation_spec))
            except (ValueError, TypeError, AttributeError) as error:
                errors.append(f"{file_path}: rules[{idx}] invalid v2 rule: {error}")

            if 'status' in r:
                raw_s = r['status']
                if not isinstance(raw_s, str) or raw_s.strip().lower() not in ('draft', 'active', 'deprecated', 'revoked'):
                    errors.append(
                        f"{file_path}: rules[{idx}] ('{rid}') invalid status '{raw_s}', must be draft, active, deprecated, or revoked"
                    )
                    rstatus = 'active'
                else:
                    rstatus = raw_s.strip().lower()
            else:
                rstatus = 'active'

            # Invariant: Live rule cannot reference inactive task
            if rstatus in ('active', 'draft') and tid and tid in known_tasks:
                t_stat = known_tasks[tid]['status']
                if t_stat not in ('active', 'testing'):
                    errors.append(
                        f"{file_path}: rules[{idx}] ('{rid}') live rule cannot reference inactive task '{tid}' (status: '{t_stat}')"
                    )

            # requirement_id links validation
            req_link = r.get('requirement_id')
            if req_link is not None:
                if not isinstance(req_link, str) or not req_link.strip():
                    errors.append(f"{file_path}: rules[{idx}] ('{rid}') 'requirement_id' must be a non-empty string when provided")
                    req_link = None
                else:
                    req_link = req_link.strip()
                    if req_link not in known_requirements:
                        errors.append(f"{file_path}: rules[{idx}] ('{rid}') links unknown requirement_id '{req_link}'")
                    else:
                        req_info = known_requirements[req_link]
                        if req_info['project_id'] != pid:
                            errors.append(
                                f"{file_path}: rules[{idx}] ('{rid}') links requirement '{req_link}' of project '{req_info['project_id']}', but rule belongs to project '{pid}'"
                            )
                        if tid and req_info['task_id'] != tid:
                            errors.append(
                                f"{file_path}: rules[{idx}] ('{rid}') links requirement '{req_link}' of task '{req_info['task_id']}', but rule belongs to task '{tid}'"
                            )
                        if not tid:
                            errors.append(
                                f"{file_path}: rules[{idx}] ('{rid}') project-level rule cannot link task-specific requirement '{req_link}'"
                            )

                        # Invariant: Live rule cannot link archived requirement
                        if rstatus in ('active', 'draft') and req_info['status'] == 'archived':
                            errors.append(
                                f"{file_path}: rules[{idx}] ('{rid}') live rule cannot link archived requirement '{req_link}'"
                            )
            else:
                req_link = None

            rule_def = {
                'id': rid,
                'project_id': pid,
                'task_id': tid,
                'title': rtitle,
                'points': tuple(points),
                'patterns': tuple(patterns),
                'priority': priority,
                'topics': topic_keys,
                'is_global': is_global,
                'priority_reason': priority_reason,
                'validation_spec': validation_spec,
                'status': rstatus,
                'requirement_id': req_link,
                'file': file_path,
            }

            if rid in known_rules:
                prior_rule = known_rules[rid]
                if (prior_rule['project_id'] != pid or prior_rule['task_id'] != tid or
                        prior_rule['title'] != rtitle or prior_rule['points'] != tuple(points) or
                        prior_rule['patterns'] != tuple(patterns) or prior_rule['priority'] != priority or
                        prior_rule['topics'] != topic_keys or prior_rule['is_global'] != is_global or
                        prior_rule['priority_reason'] != priority_reason or prior_rule['validation_spec'] != validation_spec or
                        prior_rule['status'] != rstatus or
                        prior_rule['requirement_id'] != req_link):
                    errors.append(
                        f"{file_path}: rules[{idx}] ('{rid}') conflicting duplicate rule declaration with {prior_rule['file']}"
                    )
            else:
                known_rules[rid] = rule_def

    # 4. Validate findings across all batches
    for b_idx, batch in enumerate(parsed_batches):
        file_path = batch['file']
        data = batch['data']

        raw_f_list = data.get('findings')
        f_list = raw_f_list if isinstance(raw_f_list, list) else []
        for idx, fn in enumerate(f_list):
            if not isinstance(fn, dict):
                errors.append(f"{file_path}: findings[{idx}] must be an object, got {type(fn).__name__}")
                continue

            if 'id' in fn:
                raw_fid = fn['id']
                if not isinstance(raw_fid, str) or not validate_id(raw_fid.strip()):
                    errors.append(f"{file_path}: findings[{idx}] invalid finding ID '{raw_fid}'")
                    fid = f"finding_{b_idx+1}_{idx+1}"
                else:
                    fid = raw_fid.strip()
            else:
                fid = f"finding_{b_idx+1}_{idx+1}"

            raw_ftext = fn.get('text')
            if raw_ftext is None or not isinstance(raw_ftext, str) or not raw_ftext.strip():
                errors.append(f"{file_path}: findings[{idx}] missing or empty 'text'")
                ftext = ''
            else:
                ftext = raw_ftext.strip()

            raw_pid = fn.get('project_id')
            if raw_pid is None or not isinstance(raw_pid, str) or not raw_pid.strip():
                errors.append(f"{file_path}: findings[{idx}] missing or non-string 'project_id'")
                pid = ''
            else:
                pid = raw_pid.strip()
                if pid not in known_projects:
                    errors.append(f"{file_path}: findings[{idx}] references unknown project_id '{pid}'")

            raw_tid = fn.get('task_id')
            if raw_tid is None or not isinstance(raw_tid, str) or not raw_tid.strip():
                errors.append(f"{file_path}: findings[{idx}] missing or non-string 'task_id'")
                tid = ''
            else:
                tid = raw_tid.strip()
                if tid not in known_tasks:
                    errors.append(f"{file_path}: findings[{idx}] references unknown task_id '{tid}' in project '{pid}'")
                elif known_tasks[tid]['project_id'] != pid:
                    errors.append(
                        f"{file_path}: findings[{idx}] task_id '{tid}' belongs to project '{known_tasks[tid]['project_id']}', not '{pid}'"
                    )

            target = fn.get('target_path')
            try:
                if target is not None:
                    relative_path(target, pattern=True)
            except ValueError as pe:
                errors.append(f"{file_path}: findings[{idx}] target_path invalid: {pe}")
            finding_keys = fn.get('topics', [])
            try:
                if not isinstance(finding_keys, list) or not finding_keys or any(not isinstance(key, str) for key in finding_keys):
                    raise ValueError('Findings require registered topics.')
                validate_keys(tuple(finding_keys))
            except (ValueError, TypeError) as pe:
                errors.append(f"{file_path}: findings[{idx}] invalid topics: {pe}")
                finding_keys = []
            finding_keys = tuple(sorted(finding_keys))

            if 'priority' in fn:
                raw_fp = fn['priority']
                if not isinstance(raw_fp, str) or raw_fp.strip().upper() not in ('P0', 'P1', 'P2', 'P3'):
                    errors.append(
                        f"{file_path}: findings[{idx}] ('{fid}') invalid priority '{raw_fp}', must be P0, P1, P2, or P3"
                    )
                    fpriority = 'P1'
                else:
                    fpriority = raw_fp.strip().upper()
            else:
                fpriority = 'P1'

            if 'status' in fn:
                raw_fstat = fn['status']
                if not isinstance(raw_fstat, str) or raw_fstat.strip().lower() not in (
                    'pending_review', 'approved', 'rejected', 'resolved'
                ):
                    errors.append(
                        f"{file_path}: findings[{idx}] ('{fid}') invalid status '{raw_fstat}'"
                    )
                    fstatus = 'pending_review'
                else:
                    fstatus = raw_fstat.strip().lower()
            else:
                fstatus = 'pending_review'

            finding_def = {
                'id': fid,
                'project_id': pid,
                'task_id': tid,
                'text': ftext,
                'target_path': target,
                'topics': finding_keys,
                'priority': fpriority,
                'status': fstatus,
                'file': file_path,
            }

            if fid in known_findings:
                prior_f = known_findings[fid]
                if (prior_f['project_id'] != pid or prior_f['task_id'] != tid or
                        prior_f['text'] != ftext or prior_f['target_path'] != target or
                        prior_f['topics'] != finding_keys or prior_f['priority'] != fpriority or prior_f['status'] != fstatus):
                    errors.append(
                        f"{file_path}: findings[{idx}] ('{fid}') conflicting duplicate finding declaration with {prior_f['file']}"
                    )
            else:
                known_findings[fid] = finding_def

    if errors:
        raise ValueError("Batch validation failed with errors:\n" + "\n".join(errors))

    return ValidatedBatches(
        parsed_batches,
        known_projects,
        known_tasks,
        known_requirements,
        known_rules,
        known_findings,
        known_topics
    )


def preflight_target_db(tx, projects_map, tasks_map, requirements_map, rules_map, findings_map, topics_map=None) -> PreflightResult:
    """Validate all incoming identities and payloads against existing database rows.

    Rejects any conflicting identity, cross-project collision, or unversioned snapshot rows.
    Tracks identical existing rows so subsequent ingestion skips them without duplicating audit/revisions.
    """
    result = PreflightResult()
    actor_id = DEFAULT_ACTOR_ID
    agent_client = DEFAULT_AGENT_CLIENT

    # 1. Check Projects, Worktrees, and default Sessions
    for pid, p in projects_map.items():
        row = tx.c.execute(sa.select(projects).where(projects.c.id == pid)).mappings().first()
        if row:
            if row['name'] != p['name']:
                raise ValueError(
                    f"Target DB conflict: project '{pid}' already exists with conflicting name '{row['name']}', incoming '{p['name']}'"
                )
            result.existing_projects.add(pid)

        # Worktree preflight with complete provenance check
        wt_id = worktree_id_for(pid, actor_id)
        row_wt = tx.c.execute(sa.select(worktrees).where(worktrees.c.id == wt_id)).mappings().first()
        if row_wt:
            if (row_wt['project_id'] != pid or row_wt['actor_id'] != actor_id or
                    row_wt['workspace'] != p['workspace'] or row_wt['machine_name'] != p['machine'] or
                    row_wt['platform'] != p['platform'] or row_wt['git_branch'] != p['branch'] or
                    row_wt['repo_identity'] != p['repo_identity']):
                raise ValueError(
                    f"Target DB conflict: worktree '{wt_id}' already exists with conflicting provenance attributes"
                )
            result.existing_worktrees.add(wt_id)

        # Default Project Session preflight with complete provenance check
        sess_id = project_session_id_for(pid, actor_id)
        row_s = tx.c.execute(sa.select(sessions).where(sessions.c.id == sess_id)).mappings().first()
        if row_s:
            if (row_s['project_id'] != pid or row_s['task_id'] is not None or
                    row_s['worktree_id'] != wt_id or row_s['workspace'] != p['workspace'] or
                    row_s['agent_client'] != agent_client or row_s['actor_id'] != actor_id or
                    row_s['state'] != 'active'):
                raise ValueError(
                    f"Target DB conflict: project session '{sess_id}' already exists with conflicting provenance attributes"
                )
            result.existing_sessions.add(sess_id)

    # 2. Check Tasks and Task Sessions
    for tid, t in tasks_map.items():
        row = tx.c.execute(sa.select(tasks).where(tasks.c.id == tid)).mappings().first()
        if row:
            if row['project_id'] != t['project_id']:
                raise ValueError(
                    f"Target DB conflict: task '{tid}' already exists under project '{row['project_id']}', cannot import for project '{t['project_id']}'"
                )
            if (row['title'] != t['title'] or row['description'] != t['description'] or
                    row['status'] != t['status'] or row['paused_from'] != t['paused_from']):
                raise ValueError(
                    f"Target DB conflict: task '{tid}' already exists with conflicting attributes"
                )
            result.existing_tasks.add(tid)

        # Task Session preflight with complete provenance check
        task_sess_id = task_session_id_for(t['project_id'], tid, actor_id)
        wt_id = worktree_id_for(t['project_id'], actor_id)
        p_info = projects_map[t['project_id']]
        row_ts = tx.c.execute(sa.select(sessions).where(sessions.c.id == task_sess_id)).mappings().first()
        if row_ts:
            if (row_ts['project_id'] != t['project_id'] or row_ts['task_id'] != tid or
                    row_ts['worktree_id'] != wt_id or row_ts['workspace'] != p_info['workspace'] or
                    row_ts['agent_client'] != agent_client or row_ts['actor_id'] != actor_id or
                    row_ts['state'] != 'active'):
                raise ValueError(
                    f"Target DB conflict: task session '{task_sess_id}' already exists with conflicting provenance attributes"
                )
            result.existing_sessions.add(task_sess_id)

    # 3. Check Requirements and verify version snapshot existence
    for rid, req in requirements_map.items():
        row = tx.c.execute(sa.select(requirements).where(requirements.c.id == rid)).mappings().first()
        if row:
            if (row['project_id'] != req['project_id'] or row['task_id'] != req['task_id'] or
                    row['original_text'] != req['text'] or row['status'] != req['status'] or
                    row['completion_summary'] != req['summary']):
                raise ValueError(
                    f"Target DB conflict: requirement '{rid}' already exists with conflicting attributes"
                )

            # Check that current version snapshot exists and agrees (Fixes D31 corrupt DB rows)
            curr_v = row['version']
            snap = tx.c.execute(
                sa.select(requirement_versions).where(
                    requirement_versions.c.requirement_id == rid,
                    requirement_versions.c.version == curr_v
                )
            ).mappings().first()
            if not snap:
                raise ValueError(
                    f"Target DB repair required: requirement '{rid}' exists at version {curr_v} but lacks version snapshot in requirement_versions"
                )
            if (snap['original_text'] != row['original_text'] or snap['status'] != row['status'] or
                    snap['completion_summary'] != row['completion_summary']):
                raise ValueError(
                    f"Target DB repair required: requirement '{rid}' version {curr_v} snapshot disagrees with current row"
                )

            result.existing_requirements.add(rid)

    # Topic declarations are independently explicit and compared before any writes.
    topics_map = topics_map or {}
    for identity, incoming in topics_map.items():
        old = tx.topics.get(*identity)
        if old and (old.status != 'active' or old.name != incoming.name or old.description != incoming.description):
            raise ValueError(f'Target DB conflict: topic {identity} differs or is deleted.')
    for item in [*rules_map.values(), *findings_map.values()]:
        for key in item['topics']:
            topic = tx.topics.get(item['project_id'], key) or topics_map.get((item['project_id'], key))
            if topic is None or topic.status != 'active':
                raise ValueError(f"Register or explicitly declare topic '{key}' in project '{item['project_id']}' before importing knowledge.")

    # 4. Check Rules, Requirement-Links, and verify version snapshots
    for rid, r in rules_map.items():
        row = tx.c.execute(sa.select(rules).where(rules.c.id == rid)).mappings().first()
        if row:
            points_db = tuple(json.loads(row['points_json']))
            patterns_db = tuple(json.loads(row['patterns_json']))
            if (row['project_id'] != r['project_id'] or row['task_id'] != r['task_id'] or
                    row['title'] != r['title'] or points_db != r['points'] or
                    patterns_db != r['patterns'] or row['priority'] != r['priority'] or
                    tx.knowledge.get_rule(rid).topics != r['topics'] or row['is_global'] != r['is_global'] or
                    row['priority_reason'] != r['priority_reason'] or
                    json.loads(row['validation_spec_json'] or 'null') != r['validation_spec'] or row['status'] != r['status']):
                raise ValueError(
                    f"Target DB conflict: rule '{rid}' already exists with conflicting attributes"
                )

            # Check exact requirement-link set match (do not retain or change links without audit)
            db_links = set(tx.c.execute(
                sa.select(requirement_rule_links.c.requirement_id).where(requirement_rule_links.c.rule_id == rid)
            ).scalars().all())
            expected_links = {r['requirement_id']} if r.get('requirement_id') else set()
            if db_links != expected_links:
                raise ValueError(
                    f"Target DB conflict: rule '{rid}' requirement-link set mismatch: database has {db_links or 'none'}, incoming has {expected_links or 'none'}"
                )
            if r.get('requirement_id'):
                result.existing_links.add((rid, r['requirement_id']))

            # Check version snapshot existence and agreement (Fixes D31 corrupt DB rows)
            curr_v = row['version']
            snap = tx.c.execute(
                sa.select(rule_versions).where(
                    rule_versions.c.rule_id == rid,
                    rule_versions.c.version == curr_v
                )
            ).mappings().first()
            if not snap:
                raise ValueError(
                    f"Target DB repair required: rule '{rid}' exists at version {curr_v} but lacks version snapshot in rule_versions"
                )
            snap_pts = tuple(json.loads(snap['points_json']))
            snap_pats = tuple(json.loads(snap['patterns_json']))
            if (snap['title'] != row['title'] or snap['priority'] != row['priority'] or
                    tuple(json.loads(snap['topics_json'])) != tx.knowledge.get_rule(rid).topics or
                    snap['is_global'] != row['is_global'] or snap['priority_reason'] != row['priority_reason'] or
                    snap['validation_spec_json'] != row['validation_spec_json'] or snap['status'] != row['status'] or
                    snap_pts != points_db or snap_pats != patterns_db):
                raise ValueError(
                    f"Target DB repair required: rule '{rid}' version {curr_v} snapshot disagrees with current row"
                )

            result.existing_rules.add(rid)

        # Cross-check rule task ownership in DB if task wasn't declared in this batch
        if r['task_id'] and r['task_id'] not in tasks_map:
            row_t = tx.c.execute(sa.select(tasks).where(tasks.c.id == r['task_id'])).mappings().first()
            if not row_t:
                raise ValueError(f"Target DB conflict: rule '{rid}' references unknown task '{r['task_id']}'")
            if row_t['project_id'] != r['project_id']:
                raise ValueError(
                    f"Target DB conflict: rule '{rid}' references task '{r['task_id']}' belonging to project '{row_t['project_id']}', not '{r['project_id']}'"
                )

    # 5. Check Findings
    for fid, fn in findings_map.items():
        row = tx.c.execute(sa.select(findings).where(findings.c.id == fid)).mappings().first()
        if row:
            if (row['project_id'] != fn['project_id'] or row['task_id'] != fn['task_id'] or
                    row['text'] != fn['text'] or row['target_path'] != fn['target_path'] or
                    tx.context.get_finding(fid).topics != fn['topics'] or
                    row['priority'] != fn['priority'] or row['status'] != fn['status']):
                raise ValueError(
                    f"Target DB conflict: finding '{fid}' already exists with conflicting attributes"
                )
            result.existing_findings.add(fid)

        if fn['task_id'] not in tasks_map:
            row_t = tx.c.execute(sa.select(tasks).where(tasks.c.id == fn['task_id'])).mappings().first()
            if not row_t:
                raise ValueError(f"Target DB conflict: finding '{fid}' references unknown task '{fn['task_id']}'")
            if row_t['project_id'] != fn['project_id']:
                raise ValueError(
                    f"Target DB conflict: finding '{fid}' references task '{fn['task_id']}' belonging to project '{row_t['project_id']}', not '{fn['project_id']}'"
                )

    return result


def ingest_batches(parsed_batches, db_path: str, dry_run: bool = False):
    """Insert validated batches into database atomically with complete version snapshots and revisions."""
    if not db_path:
        raise ValueError("db_path is required (never default to prod.db)")

    # Extract maps if ValidatedBatches was provided, else run validation
    if isinstance(parsed_batches, ValidatedBatches):
        projects_map = parsed_batches.projects_map
        tasks_map = parsed_batches.tasks_map
        requirements_map = parsed_batches.requirements_map
        rules_map = parsed_batches.rules_map
        findings_map = parsed_batches.findings_map
        topics_map = parsed_batches.topics_map
    else:
        files = [b['file'] for b in parsed_batches if isinstance(b, dict) and 'file' in b]
        if files:
            validated = load_and_validate(files)
            projects_map = validated.projects_map
            tasks_map = validated.tasks_map
            requirements_map = validated.requirements_map
            rules_map = validated.rules_map
            findings_map = validated.findings_map
            topics_map = validated.topics_map
        else:
            projects_map, tasks_map, requirements_map, rules_map, findings_map, topics_map = {}, {}, {}, {}, {}, {}

    uow = SqliteUnitOfWork(db_path)
    try:
        # In dry-run mode: verify target DB schema and run preflight checks (read-only, no writes)
        if dry_run:
            with uow.read() as tx:
                preflight = preflight_target_db(
                    tx, projects_map, tasks_map, requirements_map, rules_map, findings_map, topics_map
                )
            print(f"[DRY-RUN] Target database verified at {db_path} (schema: {CURRENT_SCHEMA}).")
            print(
                f"[DRY-RUN] Collision checks passed: {len(projects_map)} project(s), {len(tasks_map)} task(s), "
                f"{len(requirements_map)} requirement(s), {len(rules_map)} rule(s), {len(findings_map)} finding(s)."
            )
            print("[DRY-RUN] Validation succeeded. NO WRITES PERFORMED.")
            return

        actor_id = DEFAULT_ACTOR_ID
        agent_client = DEFAULT_AGENT_CLIENT

        # Multi-pass atomic ingestion inside a single write transaction:
        # Run identical preflight first before ANY mutation.
        with uow.write() as tx:
            preflight = preflight_target_db(
                tx, projects_map, tasks_map, requirements_map, rules_map, findings_map, topics_map
            )

            # Step 1: Projects & Worktrees & Default Sessions
            for pid, p in projects_map.items():
                if pid not in preflight.existing_projects:
                    tx.workspaces.create_project(pid, p['name'])
                    tx.audit.record(pid, actor_id, 'project.created', pid, {'source_file': p['file']})

                wt_id = worktree_id_for(pid, actor_id)
                if wt_id not in preflight.existing_worktrees:
                    worktree = Worktree(
                        id=wt_id,
                        project_id=pid,
                        actor_id=actor_id,
                        workspace=p['workspace'],
                        machine_name=p['machine'],
                        platform=p['platform'],
                        repo_identity=p['repo_identity'],
                        git_branch=p['branch'],
                    )
                    tx.workspaces.register_worktree(worktree)

                sess_id = project_session_id_for(pid, actor_id)
                if sess_id not in preflight.existing_sessions:
                    session = Session(
                        id=sess_id,
                        project_id=pid,
                        task_id=None,
                        workspace=p['workspace'],
                        worktree_id=wt_id,
                        actor_id=actor_id,
                        debug=False,
                        state='active',
                        knowledge_revision=1,
                    )
                    tx.workspaces.create_session(session, agent_client=agent_client)

            for topic in topics_map.values():
                if tx.topics.get(topic.project_id, topic.key) is None:
                    tx.topics.create(topic)
                    tx.audit.record(topic.project_id, actor_id, 'topic.created', topic.key,
                                    {'reason': 'Explicit batch topic declaration'})

            # Step 2: Tasks & Task Sessions (session task_id MUST equal task)
            for tid, t in tasks_map.items():
                if tid not in preflight.existing_tasks:
                    task = Task(
                        id=tid,
                        project_id=t['project_id'],
                        title=t['title'],
                        description=t['description'],
                        status=TaskStatus(t['status']),
                        revision=1,
                        paused_from=TaskStatus(t['paused_from']) if t.get('paused_from') else None,
                    )
                    tx.workspaces.create_task(task)
                    tx.audit.record(
                        t['project_id'], actor_id, 'task.created', tid,
                        {'title': t['title'], 'status': t['status']}
                    )

                task_sess_id = task_session_id_for(t['project_id'], tid, actor_id)
                if task_sess_id not in preflight.existing_sessions:
                    p_info = projects_map[t['project_id']]
                    wt_id = worktree_id_for(t['project_id'], actor_id)
                    tsession = Session(
                        id=task_sess_id,
                        project_id=t['project_id'],
                        task_id=tid,
                        workspace=p_info['workspace'],
                        worktree_id=wt_id,
                        actor_id=actor_id,
                        debug=False,
                        state='active',
                        knowledge_revision=1,
                    )
                    tx.workspaces.create_session(tsession, agent_client=agent_client)

            # Step 3: Requirements & Version Snapshots
            for rid, req in requirements_map.items():
                if rid not in preflight.existing_requirements:
                    req_obj = Requirement(
                        id=rid,
                        project_id=req['project_id'],
                        task_id=req['task_id'],
                        text=req['text'],
                        status=RequirementStatus(req['status']),
                        version=1,
                        summary=req.get('summary'),
                    )
                    task_sess_id = task_session_id_for(req['project_id'], req['task_id'], actor_id)
                    tx.requirements.create_requirement(
                        req_obj,
                        session_id=task_sess_id,
                        request_id=f"import-{rid}"
                    )
                    tx.audit.record(
                        req['project_id'], actor_id, 'requirement.created', rid,
                        {'task_id': req['task_id'], 'status': req['status']}
                    )

            # Step 4: Rules & Version Snapshots
            for rid, r in rules_map.items():
                if rid not in preflight.existing_rules:
                    rule_obj = Rule(
                        id=rid,
                        project_id=r['project_id'],
                        task_id=r.get('task_id'),
                        title=r['title'],
                        points=tuple(r['points']),
                        patterns=tuple(r['patterns']),
                        priority=Priority(r['priority']),
                        topics=r['topics'],
                        is_global=r['is_global'],
                        priority_reason=r['priority_reason'],
                        validation_spec=r['validation_spec'],
                        version=1,
                        status=r['status'],
                        origin_reason=None,
                    )
                    tx.topics.lock(r['project_id'], r['topics'])
                    tx.knowledge.create_rule(rule_obj)
                    tx.governance.record_review('review_imp_' + rid, r['project_id'], rid, 1,
                                                True, r['validation_spec']['basis'], actor_id)
                    tx.audit.record(
                        r['project_id'], actor_id, 'rule.created', rid,
                        {'priority': r['priority'], 'topics': r['topics'], 'basis': 'imported_normative_review'}
                    )

            # Step 5: Requirement-Rule Links
            for rid, r in rules_map.items():
                req_link = r.get('requirement_id')
                if req_link and (rid, req_link) not in preflight.existing_links:
                    tx.requirements.link_rule(req_link, rid)

            # Step 6: Findings (bound to task session)
            for fid, fn in findings_map.items():
                if fid not in preflight.existing_findings:
                    task_sess_id = task_session_id_for(fn['project_id'], fn['task_id'], actor_id)
                    finding_obj = Finding(
                        id=fid,
                        project_id=fn['project_id'],
                        task_id=fn['task_id'],
                        session_id=task_sess_id,
                        target_path=fn['target_path'],
                        text=fn['text'],
                        priority=Priority(fn['priority']),
                        version=1,
                        status=fn['status'],
                        topics=fn['topics'],
                    )
                    tx.topics.lock(fn['project_id'], fn['topics'])
                    tx.context.record_finding(finding_obj)
                    tx.audit.record(
                        fn['project_id'], actor_id, 'finding.recorded', fid,
                        {'task_id': fn['task_id'], 'target_path': fn['target_path']}
                    )

        print(f'\nSUCCESS! Ingested into {db_path}:')
        print(f'  Projects: {len(projects_map)}')
        print(f'  Tasks: {len(tasks_map)}')
        print(f'  Requirements: {len(requirements_map)}')
        print(f'  Rules: {len(rules_map)}')
        print(f'  Findings: {len(findings_map)}')
    finally:
        uow.dispose()


def main():
    parser = argparse.ArgumentParser(description="Load extracted batch results into CodeNeuro database.")
    parser.add_argument('--db', required=True, help="Path to target SQLite database (required, never default to prod.db)")
    parser.add_argument('--pattern', default='dist_batches/result_batch_*.json', help="Glob pattern for batch files")
    parser.add_argument('--files', nargs='*', help="Explicit list of batch files to import")
    parser.add_argument('--dry-run', action='store_true', help="Validate references without writing to database")
    args = parser.parse_args()

    target_files = args.files or sorted(glob.glob(args.pattern))
    if not target_files:
        print(f"No batch files found matching pattern '{args.pattern}'!", file=sys.stderr)
        sys.exit(1)

    print(f"Target database: {args.db}")
    print(f"Found {len(target_files)} batch file(s) to process.")

    try:
        batches = load_and_validate(target_files)
        ingest_batches(batches, args.db, dry_run=args.dry_run)
    except Exception as exc:
        print(f"IMPORT FAILED: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
