"""Decomposer module for breaking down PRDs / requirements into scoped rules."""

import os
import re
import uuid
from typing import Any, Dict, List, Optional
from codeneuro.models import Lifecycle, Priority, Rule, RuleStatus


class Decomposer:
    """Heuristic and LLM-assisted decomposer for transforming requirements into scoped rules."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def heuristic_decompose(
        self,
        project_id: str,
        task_id: str,
        text: str,
        known_paths: Optional[List[str]] = None,
    ) -> List[Rule]:
        """
        Fast offline heuristic breakdown of user requirement text into structured rules.
        Recognizes file patterns, priority hints, and core actionable points.
        """
        rules: List[Rule] = []
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        current_title = "任务核心规范"
        current_scopes = ["**"]
        current_priority = Priority.P1
        current_points = []

        # Keywords for priority detection
        p0_keywords = ["禁止", "千万不能", "红线", "阻断", "安全", "幂等", "支付", "密钥", "严禁", "critical", "blocking", "must not", "security"]
        p2_keywords = ["建议", "格式", "优化", "风格", "optional", "style", "prefer", "consider"]

        # Regex for detecting paths like src/xxx or file extensions
        path_pattern = re.compile(r'([a-zA-Z0-9_\-\./]+\.(?:ts|js|py|vue|jsx|tsx|go|rs|json|ya?ml|html|css))')
        dir_pattern = re.compile(r'([a-zA-Z0-9_\-\./]+/[a-zA-Z0-9_\-\./\*\?]+)')

        for line in lines:
            # Check for bullet items or numbered lists
            clean_line = re.sub(r'^[-*#\d\.\s]+', '', line).strip()
            if not clean_line:
                continue

            # Check if this line introduces a section/module
            if line.startswith("#") or line.endswith("：") or line.endswith(":"):
                if current_points:
                    rules.append(
                        Rule(
                            id=f"rule_{uuid.uuid4().hex[:8]}",
                            project_id=project_id,
                            task_id=task_id,
                            scope_patterns=current_scopes,
                            priority=current_priority,
                            lifecycle=Lifecycle.SHORT_TERM,
                            title=current_title,
                            content_points=current_points,
                            created_by="decomposer_heuristic",
                            status=RuleStatus.ACTIVE,
                        )
                    )
                    current_points = []

                current_title = clean_line.rstrip("：:")
                current_scopes = ["**"]
                current_priority = Priority.P1
                continue

            # Extract any path mentions in this line
            extracted_paths = path_pattern.findall(clean_line) + dir_pattern.findall(clean_line)
            if extracted_paths:
                current_scopes = [p if "*" in p else (p + "/**" if not p.endswith((".py", ".ts", ".js", ".vue", ".go", ".rs", ".json")) else p) for p in extracted_paths]

            # Detect priority
            lower_line = clean_line.lower()
            if any(k in lower_line for k in p0_keywords):
                line_prio = Priority.P0
            elif any(k in lower_line for k in p2_keywords):
                line_prio = Priority.P2
            else:
                line_prio = Priority.P1

            if line_prio.rank < current_priority.rank:
                current_priority = line_prio

            current_points.append(clean_line)

        if current_points:
            rules.append(
                Rule(
                    id=f"rule_{uuid.uuid4().hex[:8]}",
                    project_id=project_id,
                    task_id=task_id,
                    scope_patterns=current_scopes,
                    priority=current_priority,
                    lifecycle=Lifecycle.SHORT_TERM,
                    title=current_title,
                    content_points=current_points,
                    created_by="decomposer_heuristic",
                    status=RuleStatus.ACTIVE,
                )
            )

        return rules
