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
        'file work, and archive only Agent-confirmed completed Requirements. CodeNeuro neither '
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
        return invoke(product.workspaces.start_session, actor(ctx), project_id, workspace,
                      task_id, debug=debug, machine_name=machine_name, platform=platform,
                      repo_identity=repo_identity, git_branch=git_branch)

    @server.tool()
    def codeneuro_submit_requirement(session_id: str, text: str, ctx: Context,
                                     request_id: Optional[str] = None) -> str:
        """Persist original Requirement text under the session's selected Task."""
        return invoke(product.requirements.submit_requirement, actor(ctx), session_id, text, request_id)

    @server.tool()
    def codeneuro_get_context(session_id: str, ctx: Context,
                              file_path: Optional[str] = None, files: Optional[list[str]] = None,
                              request_id: Optional[str] = None, max_chars: int = 24000,
                              min_priority: str = 'P2', categories: Optional[list[str]] = None,
                              intent: str = 'implementing', mode: str = 'detailed') -> str:
        """Return structured content and exact rule/Requirement/Finding delivery receipts."""
        paths = tuple(files) if files is not None else (file_path,)
        try:
            query = ContextQuery(paths, Priority(min_priority), tuple(categories or ()),
                                 intent, mode, max_chars)
        except (ProductError, ValueError) as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.context.get_context, actor(ctx), session_id, query, request_id)

    @server.tool()
    def codeneuro_create_task_rule(session_id: str, title: str, content_points: list[str],
                                   scope_patterns: list[str], reason: str, ctx: Context,
                                   priority: str = 'P1', category: str = 'business',
                                   requirement_id: Optional[str] = None) -> str:
        """Create an Agent-owned draft; it is not injected until evidence validates activation."""
        try:
            selected = Priority(priority)
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.governance.create_task_rule, actor(ctx), session_id, title,
                      tuple(content_points), tuple(scope_patterns), reason, selected,
                      category, requirement_id)

    @server.tool()
    def codeneuro_report_test(session_id: str, request_id: str, command: list[str],
                              paths: list[str], exit_code: int, started_at: str,
                              finished_at: str, ctx: Context) -> str:
        """Record an actual host-reported test result; CodeNeuro never runs the command."""
        return invoke(product.governance.report_test, actor(ctx), session_id, request_id,
                      tuple(command), tuple(paths), exit_code, started_at, finished_at)

    @server.tool()
    def codeneuro_observe_rule(session_id: str, rule_id: str, expected_version: int,
                               test_report_id: str, supports: bool, reason: str,
                               ctx: Context) -> str:
        """Attach current-version supporting or contradicting client-reported evidence."""
        return invoke(product.governance.observe_rule, actor(ctx), session_id, rule_id,
                      expected_version, test_report_id, supports, reason)

    @server.tool()
    def codeneuro_mutate_task_rule(session_id: str, rule_id: str,
                                   expected_version: int, action: str, reason: str,
                                   ctx: Context, title: Optional[str] = None,
                                   content_points: Optional[list[str]] = None,
                                   scope_patterns: Optional[list[str]] = None,
                                   priority: Optional[str] = None) -> str:
        """Versioned Agent update/activate/reduce_priority/revoke of its Task Rule."""
        try:
            selected = Priority(priority) if priority is not None else None
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.governance.mutate_task_rule, actor(ctx), session_id,
                      rule_id, expected_version, action, reason, title,
                      tuple(content_points) if content_points is not None else None,
                      tuple(scope_patterns) if scope_patterns is not None else None, selected)

    @server.tool()
    def codeneuro_promote_rule(session_id: str, rule_id: str, expected_version: int,
                               reason: str, ctx: Context) -> str:
        """Promote an active Task Rule by version without widening its clauses or scope."""
        return invoke(product.knowledge.promote_rule, actor(ctx), session_id, rule_id, expected_version, reason)

    @server.tool()
    def codeneuro_propose_contract(session_id: str, target_rule_id: str,
                                  title: str, content_points: list[str],
                                  scope_patterns: list[str], priority: str,
                                  category: str, reason: str, ctx: Context) -> str:
        """Propose changing an existing long-term contract; human approval is mandatory."""
        try:
            selected = Priority(priority)
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.knowledge.propose_contract, actor(ctx), session_id,
                      target_rule_id, title, tuple(content_points),
                      tuple(scope_patterns), selected, category, reason)

    @server.tool()
    def codeneuro_archive_requirement(session_id: str, requirement_id: str,
                                      expected_version: int, summary: str, ctx: Context) -> str:
        """Archive Agent-confirmed completion; the final active demand completes its Task."""
        return invoke(product.requirements.archive_requirement, actor(ctx), session_id,
                      requirement_id, expected_version, summary)

    @server.tool()
    def codeneuro_record_finding(session_id: str, target_path: str, text: str,
                                 ctx: Context, priority: str = 'P1') -> str:
        """Record a Task-scoped unreviewed observation for matching files across sessions."""
        try:
            selected = Priority(priority)
        except ValueError as error:
            raise ToolError(f'invalid_request: {error}') from error
        return invoke(product.context.record_finding, actor(ctx), session_id, target_path, text, selected)

    @server.tool()
    def codeneuro_rate_rule(session_id: str, delivery_id: str, rule_id: str,
                            score: int, ctx: Context, reason: str = '') -> str:
        """Rate an actually delivered Rule: 0=known, 1=irrelevant, 5=core need.
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

    return server
