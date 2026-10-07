"""Standard stdio MCP tools backed by the native remote-Hub workspace client."""
from __future__ import annotations
import json
from typing import Optional
try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer
from .client import RemoteClient


def create_client_mcp(client: RemoteClient, debug_mode: Optional[bool] = None):
    debug = client.debug if debug_mode is None else debug_mode
    server = MCPServer('CodeNeuro workspace', instructions=(
        'This sidecar operates on the actual configured local worktree and a pinned authenticated Hub. '
        'Use codeneuro_read_file and codeneuro_edit_file for transparent scoped-context injection: '
        'every read returns a real delivery_id; edits check an actual diff and require preflight allow. '
        'A review_required or blocked edit has NOT written the file. Do not bypass it with another tool. '
        'Use codeneuro_run_tests for actual argv execution and captured test evidence. '
        'Test execution runs trusted repository code with the local user permissions, not an OS sandbox. '
        'When Debug is enabled, rate usefulness from real observed receipts; never manufacture scores. '
        'Call codeneuro_session_cleanup when work ends. Task completion is separate from session close.'))

    def output(value):
        return json.dumps(value, ensure_ascii=False)

    @server.tool()
    def codeneuro_list_projects() -> str:
        """List only projects authorized by this client's bearer credential."""
        return output(client.rpc('list_projects'))

    @server.tool()
    def codeneuro_list_tasks() -> str:
        """List real tasks in the configured project."""
        return output(client.rpc('list_tasks', {'project_id': client.project_id}))

    @server.tool()
    def codeneuro_create_task(title: str, description: str = '') -> str:
        """Create a real task in the configured project; bind the session explicitly before coding."""
        return output(client.rpc('create_task', {'project_id': client.project_id, 'title': title, 'description': description}))

    @server.tool()
    def codeneuro_bind_task(task_id: Optional[str], expected_revision: int) -> str:
        """Change this session task at a safe operation boundary with the current binding revision."""
        sid = client.session_id
        result = client.rpc('bind_task', {'session_id': sid, 'task_id': task_id, 'expected_revision': expected_revision})
        client.session = client.rpc('session_status', {'session_id': sid})
        return output(result)

    @server.tool()
    def codeneuro_list_active_rules() -> str:
        """List effective project contracts and current-session task rules, preserving actual versions."""
        return output(client.rpc('list_rules', {'session_id': client.session_id}))

    @server.tool()
    def codeneuro_get_graph() -> str:
        """Inspect actual code entities and dependencies indexed from this workspace."""
        session = client.start_session()
        return output(client.rpc('graph', {'project_id': client.project_id, 'worktree_id': session['worktree_id']}))

    @server.tool()
    def codeneuro_propose_contract(target_component: str, proposed_contract: str, justification: str) -> str:
        """Submit a long-term architecture contract for human review without activating it."""
        return output(client.rpc('propose_contract', {'session_id': client.session_id,
            'target_component': target_component, 'proposed_contract': proposed_contract, 'justification': justification}))

    @server.tool()
    def codeneuro_start_session() -> str:
        """Register native workspace, machine, OS and actual Git identity automatically."""
        return output(client.start_session())

    @server.tool()
    def codeneuro_read_file(file_path: str, start_line: int = 1, end_line: Optional[int] = None) -> str:
        """Read UTF-8 workspace text with automatic rule injection and SHA-256 edit token. Credential paths are excluded."""
        return output(client.read_file(file_path, start_line=start_line, end_line=end_line))

    @server.tool()
    def codeneuro_edit_file(file_path: str, new_content: str, expected_sha256: str, plan: str) -> str:
        """Replace a text file after actual-diff preflight and CAS. Use expected_sha256='missing' for new files; parent must exist. BLOCKED/REVIEW writes nothing."""
        return output(client.edit_file(file_path, new_content, expected_sha256, plan))

    @server.tool()
    def codeneuro_run_tests(command: list[str], paths: list[str], timeout_seconds: int = 120) -> str:
        """Run actual test argv in this workspace, capture exit/output and attach affected paths. No shell strings, invented results, or inherited API tokens."""
        return output(client.run_tests(command, paths, timeout_seconds=timeout_seconds))

    @server.tool()
    def codeneuro_get_context(file_path: str, request_id: Optional[str] = None, max_chars: int = 24000) -> str:
        """Get a real context receipt for an explicit file operation; read_file injects this automatically."""
        return output(client.context(file_path, request_id=request_id, max_chars=max_chars))

    @server.tool()
    def codeneuro_index_workspace() -> str:
        """Build static code metadata on this machine and upload its bounded safe manifest to the Hub."""
        return output(client.index_workspace())

    @server.tool()
    def codeneuro_record_finding(target_path: str, text: str, priority: str = 'P1') -> str:
        """Record an observed discovery in the current task with actual session provenance."""
        path, _ = client.path(target_path, allow_missing=True)
        return output(client.rpc('finding', {'session_id': client.session_id, 'target_path': path, 'text': text, 'priority': priority}))

    @server.tool()
    def codeneuro_create_rule(title: str, content_points: list[str], scope_patterns: list[str], reason: str,
                              priority: str = 'P1', activate: bool = False, evidence_ids: Optional[list[str]] = None) -> str:
        """Create a task-scoped observation or validated rule. Activation is enforced by the Hub evidence policy."""
        return output(client.rpc('create_rule', {'session_id': client.session_id, 'title': title,
            'content_points': content_points, 'scope_patterns': scope_patterns, 'reason': reason,
            'priority': priority, 'activate': activate, 'evidence_ids': evidence_ids or []}))

    @server.tool()
    def codeneuro_mutate_rule(rule_id: str, expected_version: int, action: str, reason: str,
                              title: Optional[str] = None, content_points: Optional[list[str]] = None,
                              scope_patterns: Optional[list[str]] = None, priority: Optional[str] = None) -> str:
        """Versioned task-rule update/activate/reduce_priority/revoke. Long-term changes remain human reviewed."""
        args = {'session_id': client.session_id, 'rule_id': rule_id, 'expected_version': expected_version,
                'action': action, 'reason': reason, 'title': title, 'content_points': content_points,
                'scope_patterns': scope_patterns, 'priority': priority}
        return output(client.rpc('mutate_rule', {key: value for key, value in args.items() if value is not None}))

    @server.tool()
    def codeneuro_observe_rule(rule_id: str, expected_version: int, test_run_id: str, supports: bool, reason: str) -> str:
        """Attach an actual recorded test as supporting or contradicting evidence for this rule version."""
        return output(client.rpc('observe_rule', {'session_id': client.session_id, 'rule_id': rule_id,
            'expected_version': expected_version, 'test_run_id': test_run_id, 'supports': supports, 'reason': reason}))

    @server.tool()
    def codeneuro_preflight(files: list[str], plan: str, diff: str = '') -> str:
        """Assess a multi-file plan and actual diff before acting. block/review must be resolved before edits."""
        from .client import _uid
        paths = [client.path(path, allow_missing=True)[0] for path in files]
        return output(client.rpc('preflight', {'session_id': client.session_id, 'request_id': _uid('preflight'),
                                             'files': paths, 'plan': plan, 'diff': diff}))

    @server.tool()
    def codeneuro_session_cleanup(close: bool = True, request_id: str = 'sidecar-cleanup') -> str:
        """Idempotently summarize observations/propose distillation and optionally close the real session."""
        return output(client.cleanup(close=close, request_id=request_id))

    if debug:
        @server.tool()
        def codeneuro_rate_rule(delivery_id: str, rule_id: str, score: int, reason: str) -> str:
            """Score only a real observed receipt: 0=known, 1=irrelevant, 2=low quality, 3=neutral, 4=helpful, 5=essential. Explain actual effect; no automatic positive ratings."""
            return output(client.rate_rule(delivery_id, rule_id, score, reason))

        @server.tool()
        def codeneuro_report_issue(issue_type: str, title: str, description: str, file_path: str,
                                   related_rule_ids: Optional[list[str]] = None, suggested_action: str = '') -> str:
            """Report an observed rule/scope/noise problem with session attribution. Suggestions require human review."""
            path, _ = client.path(file_path, allow_missing=True)
            return output(client.rpc('issue', {'session_id': client.session_id, 'issue_type': issue_type,
                'title': title, 'description': description, 'file_path': path,
                'related_rule_ids': related_rule_ids or [], 'suggested_action': suggested_action}))
    return server
