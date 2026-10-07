"""Evidence views shared by the workbench and authenticated remote clients."""
from __future__ import annotations
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
import json
from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from .database import DomainError
from .paths import relative_path
from .models import Lifecycle, RuleStatus, TaskStatus


def create_views_router(storage, context_service):
    router=APIRouter()
    matcher=context_service.matcher

    @router.get('/api/projects/{project_id}/inspector')
    def inspect_file(project_id: str, path: str, task_id: str | None = None,
                     worktree_id: str | None = None, days: int = Query(7, ge=1, le=90)):
        path=relative_path(path)
        with storage.transaction(write=False):
            storage.validate_scope(project_id, task_id)
            if worktree_id:
                row=storage.conn.execute('SELECT project_id FROM worktree_instances WHERE id=?', (worktree_id,)).fetchone()
                if not row or row['project_id'] != project_id:
                    raise DomainError('Worktree does not belong to this project.')
            active_task=storage.get_task(task_id) if task_id else None
            effective_task=task_id if active_task and active_task.status in (TaskStatus.ACTIVE,TaskStatus.TESTING) else None
            selected=context_service.eligible_rules(project_id,effective_task)
            long,short=matcher.filter_rules(selected,path,effective_task)
            rules=[]
            for rule in sorted([*long,*short],key=lambda r:(r.priority.rank,r.id)):
                matches=[scope for scope in rule.scope_patterns if matcher.matches_pattern(scope,path)]
                if not matches:continue
                inheritance=('项目全局' if '**' in matches else
                    '匹配文件与范围：'+', '.join(sorted(matches,key=lambda x:(x.count('/'),x))))
                rules.append({'rule':rule.model_dump(mode='json'),'matched_scopes':matches,
                              'inheritance':inheritance,'source':rule.created_by})
            cutoff=(datetime.utcnow()-timedelta(days=days)).isoformat()
            sql='''SELECT d.id,d.session_id,d.file_path,d.response_json,d.created_at,
                          a.agent_client,a.task_id,a.worktree_id
                   FROM context_deliveries d JOIN agent_sessions a ON a.id=d.session_id
                   WHERE a.project_id=? AND d.file_path=? AND d.created_at>=?'''
            params=[project_id,path,cutoff]
            if worktree_id:
                sql+=' AND a.worktree_id=?';params.append(worktree_id)
            all_rows=list(storage.conn.execute(sql+' ORDER BY d.created_at DESC',params))
            deliveries=[];stats=defaultdict(lambda:{'deliveries':0,'last_seen':None})
            for row in all_rows:
                item=dict(row)
                model=json.loads(item.pop('response_json'))
                stat=stats[item['agent_client']]
                stat['deliveries']+=1
                if stat['last_seen'] is None:stat['last_seen']=item['created_at']
                if len(deliveries)<100:
                    deliveries.append({'delivery_id':item['id'],'session_id':item['session_id'],
                                       'file_path':path,'task_id':item['task_id'],
                                       'agent_name':item['agent_client'],'worktree_id':item['worktree_id'],
                                       'created_at':item['created_at'],
                                       'rendered_markdown':model.get('rendered_markdown',''),
                                       'rule_ids':[r['id'] for r in model.get('long_term_rules',[])+model.get('short_term_rules',[])]})
            agent_stats=[{'agent_name':agent,'deliveries':value['deliveries'],
                          'last_seen':value['last_seen']} for agent,value in sorted(stats.items())]
            return {'project_id':project_id,'path':path,'task_id':effective_task,
                    'worktree_id':worktree_id,'days':days,'rules':rules,
                    'inheritance':[r['inheritance'] for r in rules],
                    'delivery_count':len(all_rows),'deliveries':deliveries,
                    'deliveries_truncated':len(all_rows)>len(deliveries),'agent_stats':agent_stats,
                    'mode':'preview','hit_count_unchanged':True}

    @router.get('/api/projects/{project_id}/events')
    async def events(project_id: str, request: Request, after: int = Query(0, ge=0),
                     last_event_id: str | None = Header(None, alias='Last-Event-ID')):
        with storage.transaction(write=False):storage.validate_scope(project_id)
        cursor=after
        if last_event_id:
            if not last_event_id.isdecimal():raise DomainError('Last-Event-ID must be a non-negative audit sequence.')
            cursor=max(cursor,int(last_event_id))
        async def stream():
            current=cursor
            yield 'retry: 1500\n\n'
            while not await request.is_disconnected():
                with storage.transaction(write=False):
                    rows=[dict(row) for row in storage.conn.execute('''SELECT sequence,project_id,actor,action,entity_id,details,created_at
                              FROM audit_events WHERE project_id=? AND sequence>? ORDER BY sequence LIMIT 100''',(project_id,current))]
                for row in rows:
                    current=row['sequence']
                    payload={'id':str(row['sequence']),'kind':row['action'],
                             'project_id':project_id,'entity_id':row['entity_id'],
                             'created_at':row['created_at'],'payload':json.loads(row['details'])}
                    yield f'id: {current}\ndata: {json.dumps(payload,ensure_ascii=False,separators=(",",":"))}\n\n'
                if not rows:
                    yield ': keepalive\n\n'
                    await asyncio.sleep(1)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})
    return router
