"""Context Synthesizer for compiling matched rules into agent-friendly prompts."""

from typing import List, Optional

from codeneuro.models import ContextResolution, Finding, Priority, Rule


class ContextSynthesizer:
    @staticmethod
    def render_markdown(
        file_path: str,
        project_id: str,
        task_id: Optional[str],
        long_term_rules: List[Rule],
        short_term_rules: List[Rule],
        findings: Optional[List[Finding]] = None,
    ) -> str:
        findings = findings or []
        lines: List[str] = []

        lines.append(f"<!-- CodeNeuro Scoped Context -->")
        lines.append(f"### [CodeNeuro Context: `{file_path}`]")
        lines.append(f"**Project**: `{project_id}`" + (f" | **Task**: `{task_id}`" if task_id else ""))
        lines.append("")

        # 1. Long-Term Architecture Contracts
        lines.append("#### 🏛️ 长期架构契约 (Persistent Architecture Contracts)")
        if not long_term_rules:
            lines.append("_此文件/模块暂无长期特殊契约，遵循通用项目标准。_")
        else:
            for rule in long_term_rules:
                badge = f"**[{rule.priority.value}]**"
                lines.append(f"- {badge} **{rule.title}**")
                for pt in rule.content_points:
                    lines.append(f"  • {pt}")
        lines.append("")

        # 2. Short-Term Task Constraints
        lines.append(f"#### ⚡ 当前任务重点约束 (Active Task Requirements)")
        if not short_term_rules:
            lines.append("_当前任务对此文件无特定短期限制。_")
        else:
            for rule in short_term_rules:
                badge = f"**[{rule.priority.value}]**"
                lines.append(f"- {badge} **{rule.title}**")
                for pt in rule.content_points:
                    lines.append(f"  • {pt}")
        lines.append("")

        # 3. Dynamic Findings from Agent Loops
        if findings:
            lines.append("#### 💡 最新排坑与运行态经验 (Live Findings)")
            for f in findings:
                lines.append(f"- **[{f.suggested_priority.value}]** `{f.target_path}`: {f.finding_text}")
            lines.append("")

        # 4. Agent Autonomous Governance Instructions
        lines.append("> ℹ️ **Agent 治理指南**:")
        lines.append("> 1. 严格遵守上述 [P0] 阻断级要求，不可擅自违反。")
        lines.append("> 2. 若在此文件排错或测试中发现新踩坑点，请调用 `codeneuro_record_finding` 沉淀。")
        lines.append("> 3. 若发现历史短期规则已过时或假设被推翻，请调用 `codeneuro_patch_rule` 标记废弃。")

        return "\n".join(lines)

    @classmethod
    def synthesize(
        cls,
        file_path: str,
        project_id: str,
        task_id: Optional[str],
        long_term_rules: List[Rule],
        short_term_rules: List[Rule],
        findings: Optional[List[Finding]] = None,
    ) -> ContextResolution:
        md = cls.render_markdown(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term_rules,
            short_term_rules=short_term_rules,
            findings=findings,
        )
        return ContextResolution(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term_rules,
            short_term_rules=short_term_rules,
            matched_findings=findings or [],
            rendered_markdown=md,
        )
