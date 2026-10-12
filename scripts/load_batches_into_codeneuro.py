#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Load extracted batch results into CodeNeuro SQLite database."""

import glob
import json
import os
import sys
from pathlib import Path

# Add src to sys.path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))

from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.adapters.sqlite.schema import (
    projects, tasks, requirements, rules, worktrees, findings, audit, sessions
)


def normalize_priority(p: str) -> str:
    p = str(p).upper()
    if 'P0' in p or 'HIGH' in p or 'CRITICAL' in p:
        return 'P0'
    if 'P1' in p or 'MEDIUM' in p or 'NORMAL' in p:
        return 'P1'
    return 'P2'


def normalize_category(c: str) -> str:
    c = str(c).lower()
    if 'sec' in c:
        return 'security'
    if 'gotcha' in c or 'pit' in c or 'bug' in c or 'warn' in c:
        return 'gotcha'
    return 'business'


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else 'prod.db'
    print(f'Ingesting into target database: {db_path}')

    files = sorted(glob.glob('dist_batches/result_batch_*.json'))
    if not files:
        print('No result_batch_*.json files found!')
        return

    uow = SqliteUnitOfWork(db_path)
    
    seen_projects = set()
    seen_tasks = set()
    seen_rules = set()
    seen_findings = set()

    total_p, total_t, total_req, total_r, total_f = 0, 0, 0, 0, 0

    with uow.engine.begin() as conn:
        for f in files:
            print(f'Loading {f}...')
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)

            # 1. Projects & Worktrees
            for p in data.get('projects', []):
                pid = p.get('id', '').strip()
                if not pid:
                    continue
                # Normalize project id
                pid = pid.replace(' ', '-').lower()[:128]
                if pid not in seen_projects:
                    pname = p.get('name') or pid
                    conn.execute(projects.insert().values(
                        id=pid,
                        name=pname[:500]
                    ))
                    seen_projects.add(pid)
                    total_p += 1

                    # Register worktree if present
                    ws = p.get('workspace') or r'D:\1\github\codeneuro'
                    branch = p.get('git_branch') or 'main'
                    conn.execute(worktrees.insert().values(
                        id=f'wt-{pid}-01',
                        project_id=pid,
                        actor_id='agent-pi',
                        workspace=ws,
                        machine_name=p.get('machine_name') or 'DevStation-Win11',
                        platform='Windows',
                        git_branch=branch
                    ))
                    conn.execute(sessions.insert().values(
                        id=f'sess-{pid}',
                        project_id=pid,
                        worktree_id=f'wt-{pid}-01',
                        task_id=None,
                        workspace=ws,
                        agent_client='pi-0.80.3',
                        actor_id='agent-pi',
                        debug=False,
                        state='active',
                        knowledge_revision=1
                    ))

            # 2. Tasks & Requirements
            for t in data.get('tasks', []):
                tid = t.get('id', '').strip()
                pid = t.get('project_id', '').strip().replace(' ', '-').lower()[:128]
                if not pid or pid not in seen_projects:
                    # fallback to first seen project
                    pid = list(seen_projects)[0] if seen_projects else 'default-project'
                    if pid not in seen_projects:
                        conn.execute(projects.insert().values(id=pid, name='默认项目'))
                        seen_projects.add(pid)

                if not tid:
                    tid = f"task_{total_t + 1}"
                tid = tid[:128]

                if tid not in seen_tasks:
                    title = t.get('title') or '未命名任务'
                    desc = t.get('description') or ''
                    status = t.get('status') or 'active'
                    if status not in ('draft', 'active', 'paused', 'testing', 'released', 'archived'):
                        status = 'active'

                    conn.execute(tasks.insert().values(
                        id=tid,
                        project_id=pid,
                        title=title[:500],
                        description=desc,
                        status=status,
                        revision=1
                    ))
                    seen_tasks.add(tid)
                    total_t += 1

                    # Insert Requirements
                    reqs = t.get('requirements', [])
                    if not reqs:
                        reqs = [{'text': title, 'status': 'active'}]

                    for r_idx, req in enumerate(reqs):
                        req_id = f"req_{tid}_{r_idx+1}"[:128]
                        r_text = req.get('text') or title
                        r_status = req.get('status') or 'active'
                        if r_status not in ('active', 'archived'):
                            r_status = 'active'
                        r_summary = req.get('summary')

                        conn.execute(requirements.insert().values(
                            id=req_id,
                            project_id=pid,
                            task_id=tid,
                            original_text=r_text,
                            status=r_status,
                            version=1,
                            completion_summary=r_summary
                        ))
                        total_req += 1

            # 3. Rules
            for r in data.get('rules', []):
                rtitle = r.get('title', '').strip()
                if not rtitle:
                    continue
                pid = r.get('project_id', '').strip().replace(' ', '-').lower()[:128]
                if not pid or pid not in seen_projects:
                    pid = list(seen_projects)[0] if seen_projects else 'default-project'

                tid = r.get('task_id')
                if tid and tid not in seen_tasks:
                    tid = None

                rid = f"rule_{total_r + 1}"
                points = r.get('points') or [rtitle]
                patterns = r.get('patterns') or ['**']
                priority = normalize_priority(r.get('priority', 'P1'))
                category = normalize_category(r.get('category', 'business'))

                conn.execute(rules.insert().values(
                    id=rid,
                    project_id=pid,
                    task_id=tid,
                    title=rtitle[:500],
                    points_json=json.dumps(points, ensure_ascii=False),
                    patterns_json=json.dumps(patterns, ensure_ascii=False),
                    priority=priority,
                    category=category,
                    status='active',
                    version=1
                ))
                seen_rules.add(rid)
                total_r += 1

            # 4. Findings
            for fn in data.get('findings', []):
                ftext = fn.get('text', '').strip()
                if not ftext:
                    continue
                pid = fn.get('project_id', '').strip().replace(' ', '-').lower()[:128]
                if not pid or pid not in seen_projects:
                    pid = list(seen_projects)[0] if seen_projects else 'default-project'

                tid = fn.get('task_id')
                if not tid or tid not in seen_tasks:
                    # find a task in this project
                    matching_tasks = [t for t in seen_tasks if t.startswith(f"t-") or True]
                    tid = matching_tasks[0] if matching_tasks else 'default-task'

                fid = f"finding_{total_f + 1}"
                target = fn.get('target_path') or 'src/**'
                priority = normalize_priority(fn.get('priority', 'P1'))

                conn.execute(findings.insert().values(
                    id=fid,
                    project_id=pid,
                    task_id=tid,
                    session_id=f'sess-{pid}',
                    target_path=target[:500],
                    text=ftext,
                    priority=priority,
                    version=1,
                    status='pending_review'
                ))
                seen_findings.add(fid)
                total_f += 1

    print(f'\nSUCCESS! Ingested into {db_path}:')
    print(f'  Projects: {total_p}')
    print(f'  Tasks: {total_t}')
    print(f'  Requirements: {total_req}')
    print(f'  Rules: {total_r}')
    print(f'  Findings: {total_f}')


if __name__ == '__main__':
    main()
