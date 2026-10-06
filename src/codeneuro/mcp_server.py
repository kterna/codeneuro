"""MCP server implementation exposing tools for coding agents with Debug mode support."""

import os
import uuid
from typing import List, Optional

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP as MCPServer
    except ImportError:
        from mcp.server import Server as MCPServer

from codeneuro.matcher import ScopeMatcher
from codeneuro.models import (
    AgentIssue,
    Finding,
    FindingStatus,
    IssueStatus,
    IssueType,
    Lifecycle,
    Priority,
    Proposal,
    Rule,
    RuleEvaluation,
    RuleStatus,
)
from codeneuro.storage import Storage
from codeneuro.synthesizer import ContextSynthesizer


def create_mcp_server(storage: Storage, debug_mode: Optional[bool] = None) -> MCPServer:
    is_debug = debug_mode if debug_mode is not None else bool(os.getenv("CODETOKEN_DEBUG", "0") in ["1", "true", "True"])

    instructions = (
        "CodeNeuro Cognitive Context Hub: Call codeneuro_get_context before editing or analyzing files "
        "to receive scoped architectural contracts and active task constraints. "
        "Use codeneuro_record_finding to record discoveries and avoid repeat pitfalls in agent loops."
    )
    if is_debug:
        instructions += (
            " [DEBUG MODE ACTIVE]: Evaluate injected rules via codeneuro_rate_rule (0=redundant/known, "
            "1=irrelevant noise, 5=essential). Report architectural conflicts or outdated rules via codeneuro_report_issue."
        )

    server = MCPServer("CodeNeuro-Hub", instructions=instructions)
    matcher = ScopeMatcher()

    @server.tool()
    def codeneuro_get_context(
        file_path: str,
        project_id: str,
        task_id: Optional[str] = None,
    ) -> str:
        """
        Query scoped architectural contracts and active task constraints for a specific file.
        Always call this before making changes to a file to adhere to project P0/P1 constraints.
        """
        all_rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        long_term, short_term = matcher.filter_rules(
            all_rules, file_path=file_path, active_task_id=task_id
        )

        # Update hit statistics
        hit_ids = [r.id for r in (long_term + short_term)]
        storage.increment_rule_hits(hit_ids)

        # Retrieve relevant findings for this path or project
        all_findings = storage.list_findings(
            project_id=project_id, status=FindingStatus.PENDING_REVIEW
        )
        matched_findings = [
            f for f in all_findings if matcher.matches_pattern(f.target_path, file_path) or f.target_path == file_path
        ]

        resolution = ContextSynthesizer.synthesize(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term,
            short_term_rules=short_term,
            findings=matched_findings,
            debug_mode=is_debug,
        )
        return resolution.rendered_markdown

    @server.tool()
    def codeneuro_record_finding(
        project_id: str,
        target_path: str,
        finding_text: str,
        task_id: Optional[str] = None,
        suggested_priority: str = "P1",
    ) -> str:
        """
        Record a critical discovery, test-failure reason, or environmental gotcha encountered during coding loops.
        This prevents subsequent agent turns from repeating the same mistake.
        """
        prio = Priority.P1
        if suggested_priority.upper() in ["P0", "P1", "P2"]:
            prio = Priority(suggested_priority.upper())

        fid = f"find_{uuid.uuid4().hex[:8]}"
        finding = Finding(
            id=fid,
            project_id=project_id,
            task_id=task_id,
            target_path=target_path,
            finding_text=finding_text,
            suggested_priority=prio,
            status=FindingStatus.PENDING_REVIEW,
        )
        storage.create_finding(finding)
        return f"Successfully recorded finding [{fid}] for '{target_path}'. It will be injected in future turns."

    @server.tool()
    def codeneuro_patch_rule(
        rule_id: str,
        action: str,
        reason: str,
    ) -> str:
        """
        Dynamically update or revoke an obsolete or invalid short-term rule when assumptions change during coding.
        action can be 'revoke' or 'deprecate'.
        """
        rule = storage.get_rule(rule_id)
        if not rule:
            return f"Error: Rule '{rule_id}' not found."

        if rule.lifecycle == Lifecycle.LONG_TERM:
            return f"Error: Rule '{rule_id}' is a long-term architectural contract and cannot be revoked by an agent directly. Please use codeneuro_propose_contract instead."

        if action.lower() == "revoke":
            storage.update_rule_status(rule_id, RuleStatus.REVOKED)
            return f"Rule '{rule_id}' ({rule.title}) has been successfully revoked. Reason: {reason}"
        elif action.lower() == "deprecate":
            storage.update_rule_status(rule_id, RuleStatus.DEPRECATED)
            return f"Rule '{rule_id}' has been marked as deprecated. Reason: {reason}"
        else:
            return f"Unsupported action '{action}'. Use 'revoke' or 'deprecate'."

    @server.tool()
    def codeneuro_propose_contract(
        project_id: str,
        target_component: str,
        proposed_contract: str,
        justification: str,
        task_id: Optional[str] = None,
    ) -> str:
        """
        Submit a proposal to promote or alter a long-term architectural contract.
        Requires human review via the WebUI dashboard.
        """
        pid = f"prop_{uuid.uuid4().hex[:8]}"
        prop = Proposal(
            id=pid,
            project_id=project_id,
            task_id=task_id,
            target_component=target_component,
            proposed_contract=proposed_contract,
            justification=justification,
            status="pending",
        )
        storage.create_proposal(prop)
        return f"Proposal [{pid}] submitted for component '{target_component}'. Awaiting human review."

    @server.tool()
    def codeneuro_list_active_rules(
        project_id: str,
        task_id: Optional[str] = None,
    ) -> str:
        """List all active rules (both long-term and current task) for overview."""
        rules = storage.list_rules(project_id=project_id, status=RuleStatus.ACTIVE)
        if task_id:
            rules = [r for r in rules if r.lifecycle == Lifecycle.LONG_TERM or r.task_id == task_id]

        if not rules:
            return f"No active rules found for project '{project_id}'."

        lines = [f"### Active Rules in Project `{project_id}`:"]
        for r in rules:
            tag = "🏛️ [LONG_TERM]" if r.lifecycle == Lifecycle.LONG_TERM else f"⚡ [TASK:{r.task_id}]"
            lines.append(f"- **{r.id}** ({tag} {r.priority.value}): **{r.title}** (Scopes: {', '.join(r.scope_patterns)})")
            for pt in r.content_points:
                lines.append(f"  * {pt}")
        return "\n".join(lines)

    # =========================================================================
    # DEBUG MODE TOOLS: Active Quality Evaluation & Issue Reflection
    # =========================================================================

    @server.tool()
    def codeneuro_rate_rule(
        project_id: str,
        rule_id: str,
        score: int,
        file_path: str,
        reason: Optional[str] = "",
        session_id: Optional[str] = None,
    ) -> str:
        """
        [Debug Mode] Rate the relevance and utility of an injected rule on a 0-5 scale.
        - 5: Essential / High Precision (exactly what was needed for this file)
        - 4: Helpful (useful context/style guidance)
        - 3: Neutral (marginally related, no harm no benefit)
        - 2: Low Quality (ambiguous or slightly misleading)
        - 1: Irrelevant Noise (completely unrelated to the file being edited)
        - 0: Redundant / Known Fatigue (already known concept, repetitive push)
        """
        if not (0 <= score <= 5):
            return f"Error: Score must be an integer between 0 and 5, got {score}."

        rule = storage.get_rule(rule_id)
        if not rule:
            return f"Error: Rule '{rule_id}' not found in project '{project_id}'."

        eval_id = f"eval_{uuid.uuid4().hex[:8]}"
        eval_item = RuleEvaluation(
            id=eval_id,
            project_id=project_id,
            rule_id=rule_id,
            score=score,
            file_path=file_path,
            reason=reason or "",
            session_id=session_id,
        )
        storage.record_evaluation(eval_item)

        meaning = {
            5: "Essential / High Precision",
            4: "Helpful",
            3: "Neutral",
            2: "Low Quality",
            1: "Irrelevant Noise",
            0: "Redundant Fatigue"
        }.get(score, "Rated")

        return f"Successfully recorded evaluation [{eval_id}] for rule '{rule_id}': {score}/5 ({meaning}). Thank you for quality feedback."

    @server.tool()
    def codeneuro_report_issue(
        project_id: str,
        issue_type: str,
        title: str,
        description: str,
        file_path: str,
        related_rule_ids: Optional[List[str]] = None,
        suggested_action: Optional[str] = "",
    ) -> str:
        """
        [Debug Mode] Actively report architectural conflicts, outdated rules, or missing guardrails encountered during coding loops.
        - issue_type: 'rule_conflict' | 'rule_outdated' | 'scope_missing' | 'noise_overflow' | 'other'
        """
        valid_types = [t.value for t in IssueType]
        type_norm = issue_type.lower()
        if type_norm not in valid_types:
            return f"Error: Invalid issue_type '{issue_type}'. Must be one of {valid_types}."

        issue_id = f"issue_{uuid.uuid4().hex[:8]}"
        issue = AgentIssue(
            id=issue_id,
            project_id=project_id,
            issue_type=IssueType(type_norm),
            title=title,
            description=description,
            file_path=file_path,
            related_rule_ids=related_rule_ids or [],
            suggested_action=suggested_action or "",
            status=IssueStatus.OPEN,
        )
        storage.record_issue(issue)

        return (
            f"Successfully filed diagnostic issue [{issue_id}] ({type_norm}) for '{file_path}'. "
            f"It has been routed to the CodeNeuro WebUI Debug Center for human/governance review."
        )

    return server
