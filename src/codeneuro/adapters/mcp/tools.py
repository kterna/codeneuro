"""One session-free MCP catalogue shared by stdio and streamable HTTP."""
from dataclasses import asdict, is_dataclass
import json
from typing import Optional

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ...modules.context import ContextQuery
from ...modules.knowledge import Priority
from ...modules.tasks import ProductError
from ...modules.workspaces import Actor
from ...workflows.product import Product
from .inputs import Action, TaskChanges, TaskState, RequirementChanges, RequirementState, Source


def create_mcp(product: Product, actor_for_context=None, *, name='CodeNeuro'):
    actor_for_context = actor_for_context or (lambda _ctx: Actor('mcp'))
    server = MCPServer(name, instructions=(
        'Project → Requirement → Task. No start/end session or session_id. '
        'List Requirements and their Tasks before creating duplicates; lists return paged summaries '
        'in items/next_cursor, and get returns full detail with bounded history. '
        'Explicitly select a Task; do not infer one from a workspace or recent call. '
        'Get context before business/file work using project_id, optional task_id and explicit priorities P0–P3. '
        'State the current situation in one line; it is recorded, never used to filter. '
        'Card Rules arrive as a complete lightweight directory of IDs, versions, titles and applicability, without bodies. '
        'Judge relevance to the current task or next action yourself, then read the relevant bodies with '
        'codeneuro_open_rules before relying on them; do not ask the user to select entries or load unrelated bodies. '
        'Reassess relevance when the task changes. Directory hints are not requirements; reading grants no action permission. '
        'Reuse registered topics via list_topics/get_topic; pure topic queries need project classification approval. '
        'Task coding completion enters testing; testing → completed needs an explicit verification_summary. '
        'All child Tasks completed only moves the Requirement to accepting. '
        'Only after explicit user overall acceptance may an Agent update the Requirement to completed, '
        'with completion_summary and a reason citing that confirmation. '
        'Archive is storage, not completion; updates/deletes require current version and reason. '
        'Source/worktree metadata is optional provenance, not authentication. '
        'The Hub never edits files, executes tests, or intercepts host tools.'))

    def actor(ctx):
        try:
            return actor_for_context(ctx)
        except ProductError as error:
            raise ToolError(f'{error.code}: {error}') from error

    def invoke(callback, *args, **kwargs):
        try:
            value = callback(*args, **kwargs)
            if is_dataclass(value):
                value = asdict(value)
                if 'markdown' in value and 'rule_refs' in value:
                    value = {key: item for key, item in value.items() if key != 'sections'}
            return json.dumps(value, ensure_ascii=False,
                default=lambda item: asdict(item) if is_dataclass(item) else str(item))
        except (ProductError, ValueError) as error:
            raise ToolError(f'{getattr(error, "code", "invalid_request")}: {error}') from error

    def fields(model):
        return model.model_dump(exclude_unset=True) if model is not None else None

    def parse_priority(value):
        try:
            return Priority(value)
        except ValueError as error:
            raise ToolError('invalid_request: Use P0, P1, P2 or P3.') from error

    @server.tool(structured_output=False)
    def codeneuro_list_projects(ctx: Context) -> str:
        """List registered projects."""
        return invoke(product.workspaces.list_projects, actor(ctx))

    @server.tool(structured_output=False)
    def codeneuro_requirement(project_id: str, action: Action, ctx: Context, id: Optional[str] = None,
            expected_version: Optional[int] = None, changes: Optional[RequirementChanges] = None,
            reason: str = '', request_id: Optional[str] = None, statuses: Optional[list[RequirementState]] = None,
            cursor: Optional[str] = None, limit: Optional[int] = None, history_cursor: Optional[int] = None,
            history_limit: int = 20, source: Optional[Source] = None) -> str:
        """Project-level business Requirement CRUD. Create needs title/text; list is paged (20, max 100).
        Get includes current content and paged history. Task completion only makes it accepting.
        Update to completed requires explicit user acceptance, completion_summary, current version and reason.
        Archive/restore separately with changes.archived; deletion is soft and requires no remaining Tasks."""
        return invoke(product.requirements.manage_requirement, actor(ctx), project_id, action, id,
            expected_version, fields(changes), reason, request_id, statuses=tuple(statuses) if statuses is not None else None,
            cursor=cursor, limit=limit, history_cursor=history_cursor, history_limit=history_limit, source=fields(source))

    @server.tool(structured_output=False)
    def codeneuro_task(project_id: str, action: Action, ctx: Context, id: Optional[str] = None,
            requirement_id: Optional[str] = None, expected_version: Optional[int] = None,
            changes: Optional[TaskChanges] = None, reason: str = '', request_id: Optional[str] = None,
            statuses: Optional[list[TaskState]] = None, cursor: Optional[str] = None, limit: Optional[int] = None,
            history_cursor: Optional[int] = None, history_limit: int = 20, source: Optional[Source] = None) -> str:
        """Child Task CRUD. Create requires a parent requirement_id; list may filter by parent/status.
        List returns items/next_cursor, 200-character summaries and truncated flags (20, max 100).
        Get returns full detail and bounded history. Coding → testing → completed needs verification_summary.
        Optional verification_report_ids must belong to this Task. Update/delete need version/reason.
        Archive is independent of completion. Reopening does not restore retired Rules."""
        return invoke(product.workspaces.manage_task, actor(ctx), project_id, action, id, expected_version,
            fields(changes), reason, requirement_id=requirement_id, statuses=tuple(statuses) if statuses is not None else None,
            cursor=cursor, limit=limit, request_id=request_id, history_cursor=history_cursor,
            history_limit=history_limit, source=fields(source))

    @server.tool(structured_output=False)
    def codeneuro_get_context(project_id: str, priorities: list[str], ctx: Context,
            task_id: Optional[str] = None, file_path: Optional[str] = None, files: Optional[list[str]] = None,
            topics: Optional[list[str]] = None, request_id: Optional[str] = None, max_chars: int = 24000,
            intent: str = 'implementing', mode: str = 'detailed', situation: str = '',
            source: Optional[Source] = None) -> str:
        """Direct project/Task context with explicit priorities; no implicit P0 or Session.
        Task queries include its parent goal and own scope, never sibling Task content.
        Supply real relative files or registered topics; topics govern relevance when present.
        situation is one recorded line about what you are doing; it never filters Rules.
        Card Rules form a complete directory of IDs, versions, titles and applicability, without bodies.
        Judge relevance to the current task or next action and read selected bodies with codeneuro_open_rules;
        do not ask the user to select entries or load unrelated bodies. Hints are not requirements.
        Same request_id replays its snapshot; new/omitted ID sees current knowledge.
        max_chars and budget_exceeded apply to the body before the directory; directory entries are never dropped."""
        if file_path is not None and files is not None:
            raise ToolError('invalid_request: Supply files or file_path, not both.')
        try:
            query = ContextQuery(tuple(parse_priority(item) for item in priorities),
                tuple(files) if files is not None else ((file_path,) if file_path else ()),
                tuple(topics or ()), intent, mode, max_chars, situation)
        except ProductError as error:
            raise ToolError(f'{error.code}: {error}') from error
        return invoke(product.context.get_context, actor(ctx), project_id, query, request_id,
                      task_id=task_id, source=fields(source))

    @server.tool(structured_output=False)
    def codeneuro_open_rules(delivery_id: str, rule_ids: list[str], reason: str, ctx: Context) -> str:
        """Read selected Rule bodies from a Delivery's on-demand directory.
        Select 1–20 distinct IDs relevant to your current task or next action, without asking the user to choose.
        Do not load unrelated bodies or infer requirements from directory hints alone.
        Only Rules recorded on that Delivery are readable; the recorded version is returned even after
        later edits. Selection is recorded once per Rule and Delivery; repeated reads return the same body."""
        return invoke(product.context.open_rules, actor(ctx), delivery_id, tuple(rule_ids), reason)

    @server.tool(structured_output=False)
    def codeneuro_get_delivery(delivery_id: str, ctx: Context) -> str:
        """Read an actual immutable Delivery by ID; return its recorded content without reassembly."""
        return invoke(product.context.get_delivery, actor(ctx), delivery_id)

    @server.tool(structured_output=False)
    def codeneuro_create_task_rule(task_id: str, title: str, content_points: list[str],
            scope_patterns: list[str], topics: list[str], validation_spec: dict, reason: str, ctx: Context,
            priority: str = 'P1', is_global: bool = False, priority_reason: str = '',
            delivery_mode: str = 'full', applies_when: str = '') -> str:
        """Create a Task-owned draft. Non-global Rules need registered topics; empty path patterns are allowed.
        validation_spec: {kind:review,basis:...} or {kind:test,checks:[{id,clause_indexes:[0],test_ids:[...]}]}.
        delivery_mode 'card' needs a one-line applies_when; 'full' leaves it empty.
        Cover every clause; P0 requires priority_reason. No originating-session ownership."""
        return invoke(product.governance.create_task_rule, actor(ctx), task_id, title, tuple(content_points),
            tuple(scope_patterns), reason, priority=parse_priority(priority), topics=tuple(topics),
            validation_spec=validation_spec, is_global=is_global, priority_reason=priority_reason,
            delivery_mode=delivery_mode, applies_when=applies_when)

    @server.tool(structured_output=False)
    def codeneuro_report_test(task_id: str, request_id: str, command: list[str], paths: list[str],
            exit_code: int, started_at: str, finished_at: str, test_cases: list[dict], ctx: Context,
            source: Optional[Source] = None) -> str:
        """Record actual host results for a Task; never execute tests. Paths may be empty.
        test_cases: [{test_id:...,status:passed|failed|skipped}]. Same event cannot add evidence twice."""
        return invoke(product.governance.report_test, actor(ctx), task_id, request_id, tuple(command),
            tuple(paths), exit_code, started_at, finished_at, tuple(test_cases), source=fields(source))

    @server.tool(structured_output=False)
    def codeneuro_observe_rule(task_id: str, rule_id: str, expected_version: int, test_report_id: str,
            supports: bool, reason: str, check_ids: list[str], ctx: Context) -> str:
        """Attach same-Task evidence to explicit checks of the current Rule version; retrieval paths are not evidence."""
        return invoke(product.governance.observe_rule, actor(ctx), task_id, rule_id, expected_version,
                      test_report_id, supports, reason, tuple(check_ids))

    @server.tool(structured_output=False)
    def codeneuro_mutate_task_rule(task_id: str, rule_id: str, expected_version: int, action: str,
            reason: str, ctx: Context, title: Optional[str] = None, content_points: Optional[list[str]] = None,
            scope_patterns: Optional[list[str]] = None, priority: Optional[str] = None,
            topics: Optional[list[str]] = None, is_global: Optional[bool] = None,
            priority_reason: Optional[str] = None, validation_spec: Optional[dict] = None,
            delivery_mode: Optional[str] = None, applies_when: Optional[str] = None) -> str:
        """Versioned update/activate/reduce_priority/revoke of a Task candidate; another Agent may continue the Task."""
        return invoke(product.governance.mutate_task_rule, actor(ctx), task_id, rule_id, expected_version,
            action, reason, title, tuple(content_points) if content_points is not None else None,
            tuple(scope_patterns) if scope_patterns is not None else None,
            parse_priority(priority) if priority is not None else None, tuple(topics) if topics is not None else None,
            is_global, priority_reason, validation_spec, delivery_mode, applies_when)

    @server.tool(structured_output=False)
    def codeneuro_promote_rule(task_id: str, rule_id: str, expected_version: int, reason: str, ctx: Context) -> str:
        """Promote an active Task Rule's exact version without widening clauses or scope; preserve validation gates."""
        return invoke(product.knowledge.promote_rule, actor(ctx), task_id, rule_id, expected_version, reason)

    @server.tool(structured_output=False)
    def codeneuro_propose_contract(task_id: str, target_rule_id: str, expected_target_version: int,
            candidate_rule_id: str, expected_candidate_version: int, reason: str, ctx: Context) -> str:
        """Propose an exact Task candidate snapshot for an existing project contract; human review remains required."""
        return invoke(product.knowledge.propose_contract, actor(ctx), task_id, target_rule_id,
            expected_target_version, candidate_rule_id, expected_candidate_version, reason)

    @server.tool(structured_output=False)
    def codeneuro_record_finding(task_id: str, text: str, topics: list[str], ctx: Context,
            target_path: Optional[str] = None, priority: str = 'P1', source: Optional[Source] = None) -> str:
        """Record an unreviewed Task observation with registered topics and optional relative path/pattern."""
        return invoke(product.context.record_finding, actor(ctx), task_id, target_path, text,
                      parse_priority(priority), topics=tuple(topics), source=fields(source))

    @server.tool(structured_output=False)
    def codeneuro_update_finding(task_id: str, finding_id: str, expected_version: int, reason: str,
            ctx: Context, topics: Optional[list[str]] = None, resolve: bool = False) -> str:
        """Reclassify or resolve a Task Finding by version; never rewrite past Deliveries."""
        return invoke(product.context.update_finding, actor(ctx), finding_id, expected_version, reason,
                      tuple(topics) if topics is not None else None, resolve, task_id=task_id)

    @server.tool(structured_output=False)
    def codeneuro_list_topics(project_id: str, ctx: Context, query: str = '', include_deleted: bool = False,
            cursor: Optional[str] = None, limit: int = 50) -> str:
        """List bounded registered project vocabulary; reuse topics instead of inventing tags."""
        return invoke(product.topics.list_topics, actor(ctx), project_id, query, include_deleted, cursor, limit)

    @server.tool(structured_output=False)
    def codeneuro_get_topic(project_id: str, key: str, ctx: Context, include_usage: bool = False) -> str:
        """Inspect a topic version, immutable boundary and optionally blocking references."""
        return invoke(product.topics.get_topic, actor(ctx), project_id, key, include_usage)

    @server.tool(structured_output=False)
    def codeneuro_create_topic(project_id: str, key: str, name: str, description: str, reason: str, ctx: Context) -> str:
        """Explicitly register a project topic after checking definitions; keys cannot be reused."""
        return invoke(product.topics.create_topic, actor(ctx), key, name, description, reason, project_id=project_id)

    @server.tool(structured_output=False)
    def codeneuro_update_topic(project_id: str, key: str, expected_version: int, reason: str,
            ctx: Context, name: Optional[str] = None, description: Optional[str] = None) -> str:
        """Versioned topic metadata update; referenced boundaries and keys remain immutable."""
        return invoke(product.topics.update_topic, actor(ctx), key, expected_version, reason,
                      name, description, project_id=project_id)

    @server.tool(structured_output=False)
    def codeneuro_delete_topic(project_id: str, key: str, expected_version: int, reason: str, ctx: Context) -> str:
        """Soft-delete an unreferenced project topic without cascading or changing history."""
        return invoke(product.topics.delete_topic, actor(ctx), key, expected_version, reason, project_id=project_id)

    @server.tool(structured_output=False)
    def codeneuro_rate_rule(delivery_id: str, rule_id: str, score: int, ctx: Context, reason: str = '') -> str:
        """Rate an actually delivered Rule 0–5. 0=known (statistics only), 1=noise, 2=low utility,
        3=useful, 4=important, 5=critical. No debug mode; feedback never hides another Agent's content."""
        return invoke(product.feedback.rate_rule, actor(ctx), delivery_id, rule_id, score, reason)

    @server.tool(structured_output=False)
    def codeneuro_report_issue(project_id: str, issue_type: str, title: str, description: str, ctx: Context,
            task_id: Optional[str] = None, file_path: Optional[str] = None,
            related_rule_ids: Optional[list[str]] = None, suggested_action: str = '') -> str:
        """Report observed conflict/noise/coverage issues; no debug mode. Conflicts require a Task and two Rules."""
        return invoke(product.feedback.report_issue, actor(ctx), project_id, issue_type, title, description,
                      file_path, tuple(related_rule_ids or ()), suggested_action, task_id=task_id)

    # The SDK otherwise ignores unknown arguments; obsolete session_id must fail explicitly.
    for tool in server._tool_manager.list_tools():
        model = tool.fn_metadata.arg_model
        model.model_config['extra'] = 'forbid'
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)
    return server
