"""Compact context rendering. IDs and versions remain visible outside debug mode."""
from .models import ContextResolution


class ContextSynthesizer:
    @staticmethod
    def render_markdown(file_path,project_id,task_id,long_term_rules,short_term_rules,findings=None,debug_mode=False):
        lines=[f'### [CodeNeuro Context: `{file_path}`]',f'Project: `{project_id}` | Task: `{task_id or "none"}`']
        for heading,rules in [('长期架构契约',long_term_rules),('当前任务重点约束',short_term_rules)]:
            if not rules:continue
            lines.append('\n#### '+heading)
            for rule in rules:
                lines.append(f'- [{rule.priority.value}] `{rule.id}` v{rule.version} — {rule.title}')
                lines.extend('  - '+point for point in rule.content_points)
        if findings:
            lines.append('\n#### 最新排坑与运行态经验（待审，需核实，不覆盖已批准规则）')
            lines.extend(f'- `{f.id}`: {f.finding_text}' for f in findings)
        lines.append('\nAgent 治理指南：变更前核对规则；发现用 codeneuro_record_finding 记录，长期契约变更须提案。')
        if debug_mode:
            lines.append('[DEBUG MODE ACTIVE] 通过 codeneuro_rate_rule 评价实际下发：0=已知，1=无关，5=需要；使用 delivery_id。')
        return '\n'.join(lines)

    @classmethod
    def synthesize(cls,file_path,project_id,task_id,long_term_rules,short_term_rules,findings=None,debug_mode=False):
        return ContextResolution(file_path=file_path,project_id=project_id,task_id=task_id,
            long_term_rules=long_term_rules,short_term_rules=short_term_rules,matched_findings=findings or [],debug_mode=debug_mode,
            rendered_markdown=cls.render_markdown(file_path,project_id,task_id,long_term_rules,short_term_rules,findings,debug_mode))
