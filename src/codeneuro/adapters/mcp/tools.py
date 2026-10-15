"""One MCP tool catalogue shared by stdio and streamable HTTP."""
from __future__ import annotations

from dataclasses import asdict
import json
from typing import Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ...modules.context import ContextQuery
from ...modules.knowledge import Priority
from ...modules.tasks import ProductError
from ...modules.workspaces import Actor
from ...workflows.product import Product


def create_mcp(product: Product, actor_for_context=None, *, name: str = 'CodeNeuro') -> MCPServer:
    """Expose the same tools with no transport credentials."""
    if actor_for_context is None:
        actor_for_context = lambda _ctx: Actor('mcp')
    server = MCPServer(name, instructions=(
        'List Tasks first. Match active Task titles/descriptions locally using regex; choose explicitly '
        'when several match. Submit original demand text to a bound Task, call get_context before '
        'file or business work with explicit priorities (P0-P3). Reuse registered project topics from '
        'the session catalogue; topic-only queries do not require dummy files. Archive only '
        'Agent-confirmed completed Requirements. CodeNeuro neither '
        'edits files nor runs tests. A standard MCP installation does not intercept host tools.'))

    def output(value):
        return json.dumps(asdict(value) if hasattr(value, '__dataclass_fields__') else value,
                          ensure_ascii=False, default=str)

    def actor(ctx):
        try:
            return actor_for_context(ctx)
        except ProductError as error:
            raise ToolError(f'{error.code}: {error}') from error

    def invoke(callback, *args, **kwargs):
        try:
            return output(callback(*args, **kwargs))
        except ProductError as error:
            raise ToolError(f'{error.code}: {error}') from error

    @server.tool()
    def codeneuro_list_projects(ctx: Context) -> str:
        """List registered projects."""
        return invoke(product.workspaces.list_projects, actor(ctx))

    @server.tool()
    def codeneuro_list_tasks(project_id: str, ctx: Context) -> str:
        """Return real Task titles/descriptions/states for Agent-side regex matching."""
        return invoke(product.workspaces.list_tasks, actor(ctx), project_id)

    @server.tool()
    def codeneuro_create_task(project_id: str, title: str, ctx: Context,
                              description: str = '', initial_status: str = 'active') -> str:
        """Create a new Task only after checking existing Task candidates."""
        return invoke(product.workspaces.create_task, actor(ctx), project_id, title, description, initial_status)

    @server.tool()
    def codeneuro_start_session(project_id: str, workspace: str, ctx: Context,
                                task_id: Optional[str] = None, debug: bool = False,
                                machine_name: str = 'not_attested', platform: str = 'unknown',
                                repo_identity: Optional[str] = None, git_branch: str = '') -> str:
        """Pin a session to a client-attested worktree; Hub cannot inspect remote files.
        Note: debug=True is required if the session will provide rule ratings/feedback
        (codeneuro_rate_rule) or report issues (codeneuro_report_issue). Production sessions
        default to debug=False to avoid diagnostic pollution."""
        def start():
            who = actor(ctx)
            session = product.workspaces.start_session(who, project_id, workspace, task_id,
                debug=debug, machine_name=machine_name, platform=platform,
                repo_identity=repo_identity, git_branch=git_branch)
            return {**asdict(session), 'protocol_version': 2,
                    'topic_catalog': product.topics.list_topics(who, project_id, limit=30)}
        return invoke(start)

    @server.tool()
    def codeneuro_submit_requirement(session_id: str, text: str, ctx: Context,
                                     request_id: Optional[str] = None) -> str:
        """Persist original Requirement text under the session's selected Task."""
        return invoke(product.requirements.submit_requirement, actor(ctx), session_id, text, request_id)

    @server.tool()
    def codeneuro_get_context(session_id: str, priorities: list[str], ctx: Context,
                              file_path: Optional[str] = None, files: Optional[list[str]] = None,
                              topics: Optional[list[str]] = None, request_id: Optional[str] = None,
                              max_chars: int = 24000, intent: str = 'implementing', mode: str = 'detailed') -> str:
        """V2: explicitly select priority levels (no defaults/threshold/implicit P0).
        Topics define business focus; paths only rank within that focus. Without topics,
        real paths determine applicability. Pure-topic queries need project cutover approval."""
        try:
            if files is not None and file_path is not None:
                raise ProductError('Supply files or file_path, not both.')
            paths = tuple(files) if files is not None else ((file_path,) if file_path is not None else ())
            query = ContextQuery(priorities=tuple(Priority(p) for p in priorities), files=paths,
                                 topics=tuple(topics or ()), intent=intent, mode=mode, max_chars=max_chars)
        except (ProductError, ValueError) as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.context.get_context, actor(ctx), session_id, query, request_id)

    @server.tool()
    def codeneuro_create_task_rule(session_id: str, title: str, content_points: list[str],
                                   scope_patterns: list[str], topics: list[str], validation_spec: dict,
                                   reason: str, ctx: Context, priority: str = 'P1',
                                   requirement_id: Optional[str] = None, is_global: bool = False,
                                   priority_reason: str = '') -> str:
        """Create a topic-bound draft (empty scope_patterns is allowed).
        validation_spec is {kind: review, basis: ...} for human normative review, or
        {kind: test, checks: [{id, clause_indexes: [0], test_ids: [...]}]} covering every clause.
        P0 requires priority_reason; a non-global rule requires registered topics."""
        try:
            selected = Priority(priority)
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.governance.create_task_rule, actor(ctx), session_id, title,
                      tuple(content_points), tuple(scope_patterns), reason, topics=tuple(topics),
                      validation_spec=validation_spec, priority=selected, requirement_id=requirement_id, is_global=is_global,
                      priority_reason=priority_reason)

    @server.tool()
    def codeneuro_report_test(session_id: str, request_id: str, command: list[str],
                              paths: list[str], exit_code: int, started_at: str,
                              finished_at: str, test_cases: list[dict], ctx: Context) -> str:
        """Record actual host results, never execute tests. paths may be empty;
        test_cases requires [{test_id: ..., status: passed|failed|skipped}]."""
        return invoke(product.governance.report_test, actor(ctx), session_id, request_id,
                      tuple(command), tuple(paths), exit_code, started_at, finished_at, tuple(test_cases))

    @server.tool()
    def codeneuro_observe_rule(session_id: str, rule_id: str, expected_version: int,
                               test_report_id: str, supports: bool, reason: str,
                               check_ids: list[str], ctx: Context) -> str:
        """Attach evidence to explicit validation checks, never merely a retrieval path."""
        return invoke(product.governance.observe_rule, actor(ctx), session_id, rule_id,
                      expected_version, test_report_id, supports, reason, tuple(check_ids))

    @server.tool()
    def codeneuro_mutate_task_rule(session_id: str, rule_id: str,
                                   expected_version: int, action: str, reason: str,
                                   ctx: Context, title: Optional[str] = None,
                                   content_points: Optional[list[str]] = None,
                                   scope_patterns: Optional[list[str]] = None,
                                   priority: Optional[str] = None, topics: Optional[list[str]] = None,
                                   is_global: Optional[bool] = None, priority_reason: Optional[str] = None,
                                   validation_spec: Optional[dict] = None) -> str:
        """Versioned Agent update/activate/reduce_priority/revoke of its Task Rule."""
        try:
            selected = Priority(priority) if priority is not None else None
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.governance.mutate_task_rule, actor(ctx), session_id,
                      rule_id, expected_version, action, reason, title,
                      tuple(content_points) if content_points is not None else None,
                      tuple(scope_patterns) if scope_patterns is not None else None, selected,
                      tuple(topics) if topics is not None else None, is_global, priority_reason, validation_spec)

    @server.tool()
    def codeneuro_promote_rule(session_id: str, rule_id: str, expected_version: int,
                               reason: str, ctx: Context) -> str:
        """Promote an active Task Rule by version without widening its clauses or scope."""
        return invoke(product.knowledge.promote_rule, actor(ctx), session_id, rule_id, expected_version, reason)

    @server.tool()
    def codeneuro_propose_contract(session_id: str, target_rule_id: str, expected_target_version: int,
                                  candidate_rule_id: str, expected_candidate_version: int,
                                  reason: str, ctx: Context) -> str:
        """Propose an exact Task candidate snapshot for an existing contract; human review remains mandatory."""
        return invoke(product.knowledge.propose_contract, actor(ctx), session_id, target_rule_id,
                      expected_target_version, candidate_rule_id, expected_candidate_version, reason)

    @server.tool()
    def codeneuro_archive_requirement(session_id: str, requirement_id: str,
                                      expected_version: int, summary: str, ctx: Context) -> str:
        """Archive Agent-confirmed completion; the final active demand completes its Task."""
        return invoke(product.requirements.archive_requirement, actor(ctx), session_id,
                      requirement_id, expected_version, summary)

    @server.tool()
    def codeneuro_record_finding(session_id: str, text: str, topics: list[str],
                                 ctx: Context, target_path: Optional[str] = None, priority: str = 'P1') -> str:
        """Record a Task-scoped unreviewed observation for matching topics/files across sessions."""
        try:
            selected = Priority(priority)
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.context.record_finding, actor(ctx), session_id, target_path, text, selected, topics=tuple(topics))

    @server.tool()
    def codeneuro_update_finding(session_id: str, finding_id: str, expected_version: int,
                                 reason: str, ctx: Context, topics: Optional[list[str]] = None,
                                 resolve: bool = False) -> str:
        """Explicitly reclassify or resolve a Task Finding; never rewrite past Deliveries."""
        return invoke(product.context.update_finding, actor(ctx), finding_id, expected_version, reason,
                      tuple(topics) if topics is not None else None, resolve, session_id=session_id)

    @server.tool()
    def codeneuro_list_topics(project_id: str, ctx: Context, query: str = '',
                              include_deleted: bool = False, cursor: Optional[str] = None, limit: int = 50) -> str:
        """List the project's registered vocabulary; reuse topics instead of silently inventing tags."""
        return invoke(product.topics.list_topics, actor(ctx), project_id, query, include_deleted, cursor, limit)

    @server.tool()
    def codeneuro_get_topic(project_id: str, key: str, ctx: Context, include_usage: bool = False) -> str:
        """Inspect a topic version, immutable boundary and optionally blocking references."""
        return invoke(product.topics.get_topic, actor(ctx), project_id, key, include_usage)

    @server.tool()
    def codeneuro_create_topic(session_id: str, key: str, name: str, description: str,
                               reason: str, ctx: Context) -> str:
        """Explicitly register a new project topic after checking existing definitions; keys cannot be reused."""
        return invoke(product.topics.create_topic, actor(ctx), key, name, description, reason, session_id=session_id)

    @server.tool()
    def codeneuro_update_topic(session_id: str, key: str, expected_version: int, reason: str,
                               ctx: Context, name: Optional[str] = None, description: Optional[str] = None) -> str:
        """Versioned metadata update; referenced topic boundaries and all keys are immutable."""
        return invoke(product.topics.update_topic, actor(ctx), key, expected_version, reason,
                      name, description, session_id=session_id)

    @server.tool()
    def codeneuro_delete_topic(session_id: str, key: str, expected_version: int,
                               reason: str, ctx: Context) -> str:
        """Soft-delete an unreferenced topic; never cascade, merge, or reinterpret its history."""
        return invoke(product.topics.delete_topic, actor(ctx), key, expected_version, reason, session_id=session_id)

    @server.tool()
    def codeneuro_rate_rule(session_id: str, delivery_id: str, rule_id: str,
                            score: int, ctx: Context, reason: str = '') -> str:
        """Rate an actually delivered Rule on a scale from 0 to 5:
        - 0 (Known): Already known; this session/version may condense, but applicable selected P0 stays full.
        - 1 (Noise): Irrelevant or noisy rule for current task/files.
        - 2 (Low Utility): Weakly relevant; minor reference value but not necessary.
        - 3 (Useful): Helpful best practice or standard guideline.
        - 4 (Important): Significant project standard or gotcha prevention that avoids rework.
        - 5 (Critical): Indispensable architectural redline or core business contract.
        Requires the session to have been started with debug=True."""
        return invoke(product.feedback.rate_rule, actor(ctx), session_id, delivery_id, rule_id, score, reason)

    @server.tool()
    def codeneuro_report_issue(session_id: str, issue_type: str, title: str,
                               description: str, file_path: str, ctx: Context,
                               related_rule_ids: Optional[list[str]] = None,
                               suggested_action: str = '') -> str:
        """Report an observed conflict/noise/coverage issue for human review.
        Requires the session to have been started with debug=True."""
        return invoke(product.feedback.report_issue, actor(ctx), session_id, issue_type,
            title, description, file_path, tuple(related_rule_ids or ()), suggested_action)

    @server.tool()
    def codeneuro_end_session(session_id: str, ctx: Context) -> str:
        """Close this caller's session; this does not complete a Task."""
        return invoke(product.workspaces.end_session, actor(ctx), session_id)

    # The pinned SDK otherwise ignores unknown arguments. Reject obsolete category/min_priority
    # instead of silently widening a caller's intended query; keep this SDK detail in the adapter.
    for tool in server._tool_manager.list_tools():
        model = tool.fn_metadata.arg_model
        model.model_config['extra'] = 'forbid'
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)
    return server
