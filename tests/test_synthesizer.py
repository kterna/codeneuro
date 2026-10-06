"""Unit tests for Context Synthesizer."""

from codeneuro.models import Finding, Lifecycle, Priority, Rule
from codeneuro.synthesizer import ContextSynthesizer


def test_synthesizer_render_format():
    r_long = Rule(
        id="r1",
        project_id="p1",
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Zero Float Math Rule",
        content_points=["Must use safe_calc()"],
    )
    r_short = Rule(
        id="r2",
        project_id="p1",
        task_id="task_001",
        priority=Priority.P1,
        lifecycle=Lifecycle.SHORT_TERM,
        title="Adapt new split parameter",
        content_points=["Support split_count optional field"],
    )
    finding = Finding(
        id="f1",
        project_id="p1",
        target_path="src/pay/calc.ts",
        finding_text="Jest test suite requires crypto shim",
        suggested_priority=Priority.P1,
    )

    resolution = ContextSynthesizer.synthesize(
        file_path="src/pay/calc.ts",
        project_id="p1",
        task_id="task_001",
        long_term_rules=[r_long],
        short_term_rules=[r_short],
        findings=[finding],
    )

    md = resolution.rendered_markdown
    assert "### [CodeNeuro Context: `src/pay/calc.ts`]" in md
    assert "长期架构契约" in md
    assert "[P0]" in md
    assert "Zero Float Math Rule" in md
    assert "当前任务重点约束" in md
    assert "Adapt new split parameter" in md
    assert "最新排坑与运行态经验" in md
    assert "Jest test suite requires crypto shim" in md
    assert "Agent 治理指南" in md
