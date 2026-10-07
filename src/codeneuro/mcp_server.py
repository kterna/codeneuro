"""Stdio MCP adapter. All context and feedback policy lives in ContextService."""
import json
import os
from typing import Optional
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer
from .database import DomainError
from .models import AgentIssue, IssueType, Lifecycle, Priority, Proposal, Rule, RuleStatus, Task
from .paths import relative_path
from .service import ContextService, uid


def create_mcp_server(storage, debug_mode: Optional[bool] = None):
    debug = debug_mode if debug_mode is not None else os.getenv('CODENEURO_DEBUG', os.getenv('CODETOKEN_DEBUG', '0')).lower() in ('1', 'true')
    service = ContextService(storage)
    server = MCPServer('CodeNeuro', instructions=(
        'Start with codeneuro_list_projects, then codeneuro_start_session for the actual workspace and task. '
        'Call codeneuro_get_context before reading or changing a file. Registering MCP alone does not '
        'install file hooks. Use returned delivery_id for feedback. Short-term findings are scoped to '
        'your task and session. Long-term changes require human review. Close the session when done.'))

    @server.tool()
    def codeneuro_list_projects() -> str:
        """List registered projects and workspace roots. Does not create sample data."""
        return json.dumps([p.model_dump(mode='json') for p in storage.list_projects()], ensure_ascii=False)

    @server.tool()
    def codeneuro_create_task(project_id: str, title: str, description: str = '') -> str:
        """Create an isolated coding task before starting its session."""
        task = storage.create_task(Task(id=uid('task'), project_id=project_id, title=title, description=description))
        return task.model_dump_json()

    @server.tool()
    def codeneuro_start_session(project_id: str, workspace_path: str, task_id: Optional[str] = None,
                               agent_client: str = 'MCP') -> str:
        """Register the real local project/worktree and pin this session to a task."""
        return json.dumps(service.start_session(project_id, workspace_path, task_id, agent_client, debug))

    @server.tool()
    def codeneuro_get_context(session_id: str, file_path: str, request_id: Optional[str] = None,
                             max_chars: int = 24000) -> str:
        """Deliver scoped rules before file access; reuse request_id only when retrying the same request."""
        return service.resolve(session_id=session_id, file_path=file_path, request_id=request_id,
                               max_chars=max_chars).rendered_markdown

    @server.tool()
    def codeneuro_end_session(session_id: str) -> str:
        """Close this agent session. This does not mark the task completed."""
        return json.dumps(service.close_session(session_id))

    @server.tool()
    def codeneuro_record_finding(session_id: str, target_path: str, finding_text: str,
                                suggested_priority: str = 'P1') -> str:
        """Record an observed discovery with its source session. Do not submit invented measurements."""
        return service.record_finding(session_id, target_path, finding_text, suggested_priority).model_dump_json()

    @server.tool()
    def codeneuro_patch_rule(session_id: str, rule_id: str, action: str, reason: str,
                            expected_version: int) -> str:
        """Revoke/deprecate a short-term rule belonging to this session's task; include the observed version."""
        with storage.transaction():
            session = service._session(session_id)
            rule = storage.get_rule(rule_id)
            if rule is None or rule.project_id != session['project_id'] or rule.task_id != session['task_id']:
                raise DomainError('Rule is outside this session task.')
            if rule.lifecycle == Lifecycle.LONG_TERM:
                raise DomainError('Long-term contracts require human review.', 'review_required', 403)
            states = {'revoke': RuleStatus.REVOKED, 'deprecate': RuleStatus.DEPRECATED}
            if action not in states or not reason.strip():
                raise DomainError('Supply revoke/deprecate and a non-empty reason.')
            storage.update_rule_status(rule_id, states[action], expected_version)
            storage.audit(rule.project_id, session_id, 'rule.agent_status', rule_id, {'reason': reason})
            return storage.get_rule(rule_id).model_dump_json()

    @server.tool()
    def codeneuro_propose_rules(session_id: str, rules: list[dict]) -> str:
        """Submit structured PRD rules as drafts. Humans review scopes/priority before activation."""
        with storage.transaction():
            session = service._session(session_id)
            storage.validate_scope(session['project_id'], session['task_id'], require_active=True)
            if not session['task_id'] or not 1 <= len(rules) <= 100:
                raise DomainError('A task and between 1 and 100 candidate rules are required.')
            result = []
            for data in rules:
                item = Rule(id=uid('rule'), project_id=session['project_id'], task_id=session['task_id'],
                            title=data['title'], content_points=data['content_points'],
                            scope_patterns=data['scope_patterns'], priority=Priority(data.get('priority', 'P1')),
                            status=RuleStatus.DRAFT, created_by=session_id)
                result.append(storage.create_rule(item).model_dump(mode='json'))
            return json.dumps(result, ensure_ascii=False)

    @server.tool()
    def codeneuro_propose_contract(session_id: str, target_component: str, proposed_contract: str,
                                  justification: str) -> str:
        """Propose a long-term contract for human review, without activating it."""
        with storage.transaction():
            session = service._session(session_id)
            item = Proposal(id=uid('proposal'), project_id=session['project_id'], task_id=session['task_id'],
                            target_component=relative_path(target_component, pattern=True),
                            proposed_contract=proposed_contract, justification=justification)
            return storage.create_proposal(item).model_dump_json()

    @server.tool()
    def codeneuro_list_active_rules(session_id: str) -> str:
        """List only project contracts and active rules for this session's task."""
        with storage.transaction(write=False):
            session = service._session(session_id)
            return json.dumps([r.model_dump(mode='json') for r in service.eligible_rules(session['project_id'], session['task_id'])], ensure_ascii=False)

    if debug:
        @server.tool()
        def codeneuro_rate_rule(session_id: str, delivery_id: str, rule_id: str, score: int, reason: str = '') -> str:
            """Rate an actual delivery: 0=already known, 1=irrelevant, 2-4=partial usefulness, 5=needed. Idempotent per delivery/rule."""
            return json.dumps(service.evaluate(session_id=session_id, delivery_id=delivery_id, rule_id=rule_id, score=score, reason=reason))

        @server.tool()
        def codeneuro_report_issue(session_id: str, issue_type: str, title: str, description: str,
                                   file_path: str, related_rule_ids: Optional[list[str]] = None,
                                   suggested_action: str = '') -> str:
            """Report observed scope/quality problems with actual session attribution."""
            with storage.transaction():
                session = service._session(session_id)
                if not session['debug']:
                    raise DomainError('Debug feedback is disabled for this session.', 'debug_disabled', 403)
                item = AgentIssue(id=uid('issue'), project_id=session['project_id'], session_id=session_id,
                    issue_type=IssueType(issue_type), title=title, description=description,
                    file_path=relative_path(file_path), related_rule_ids=related_rule_ids or [],
                    suggested_action=suggested_action, source='agent')
                return storage.record_issue(item).model_dump_json()
    return server
