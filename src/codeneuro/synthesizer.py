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
        debug_mode: bool = False,
    ) -> str:
        findings = findings or []
        lines: List[str] = []

        lines.append(f"<!-- CodeNeuro Scoped Context -->")
        lines.append(f"### [CodeNeuro Context: `{file_path}`]")
        lines.append(f"**Project**: `{project_id}`" + (f" | **Task**: `{task_id}`" if task_id else ""))
        if debug_mode:
            lines.append("`[DEBUG MODE ACTIVE]` 规则自适应质量评测与主动反馈已开启")
        lines.append("")

        # 1. Long-Term Architecture Contracts
        lines.append("#### 🏛️ 长期架构契约 (Persistent Architecture Contracts)")
        if not long_term_rules:
            lines.append("_此文件/模块暂无长期特殊契约，遵循通用项目标准。_")
        else:
            for rule in long_term_rules:
                badge = f"**[{rule.priority.value}]**"
                rule_tag = f"`{rule.id}`" if debug_mode else ""
                lines.append(f"- {badge} {rule_tag} **{rule.title}**")
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
                rule_tag = f"`{rule.id}`" if debug_mode else ""
                lines.append(f"- {badge} {rule_tag} **{rule.title}**")
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

        # 5. Debug Mode Active Directives
        if debug_mode:
            lines.append("")
            lines.append("---")
            lines.append("> 🛠️ **[CodeNeuro Debug 模式诊断提示]**:")
            lines.append("> - **规则有效性质检**: 请对上述下发规则调用 `codeneuro_rate_rule(rule_id, score, file_path, reason)` 评分:")
            lines.append(">   • `5分`: 正是当前编码所急需的决策依据/安全红线 (高价值)")
            lines.append(">   • `4分`: 有辅助价值的代码风格/逻辑参考")
            lines.append(">   • `3分`: 勉强相关的中性规则")
            lines.append(">   • `2分`: 描述有歧义或轻度误导")
            lines.append(">   • `1分`: 完全不相关的噪音规则 (需排查 Glob 匹配范围)")
            lines.append(">   • `0分`: 我已知晓，此规则重复推送造成认知疲劳")
            lines.append("> - **架构异常主动报告**: 若发现规则间互斥冲突、规则严重过时或存在重大暗礁盲区，请调用 `codeneuro_report_issue(...)` 主动反馈。")

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
        debug_mode: bool = False,
    ) -> ContextResolution:
        md = cls.render_markdown(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term_rules,
            short_term_rules=short_term_rules,
            findings=findings,
            debug_mode=debug_mode,
        )
        return ContextResolution(
            file_path=file_path,
            project_id=project_id,
            task_id=task_id,
            long_term_rules=long_term_rules,
            short_term_rules=short_term_rules,
            matched_findings=findings or [],
            rendered_markdown=md,
            debug_mode=debug_mode,
        )
