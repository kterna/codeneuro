"""Unit tests for RuleExporter."""

import pytest
from pathlib import Path
from codeneuro.exporter import RuleExporter
from codeneuro.models import Lifecycle, Priority, Rule, RuleStatus


def test_export_cursor_rules(tmp_path: Path):
    r1 = Rule(
        id="r_p0",
        project_id="proj1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Payment Security Redline",
        content_points=["No DB I/O in calc", "Check hash signature"],
        status=RuleStatus.ACTIVE
    )
    r2 = Rule(
        id="r_task",
        project_id="proj1",
        task_id="task_split",
        scope_patterns=["src/pay/split.py"],
        priority=Priority.P1,
        lifecycle=Lifecycle.SHORT_TERM,
        title="Split parameter adaptation",
        content_points=["Support 3-way split"],
        status=RuleStatus.ACTIVE
    )

    paths = RuleExporter.export_cursor_rules([r1, r2], out_dir=tmp_path, active_task_id="task_split")
    assert len(paths) == 2

    # Check content of first rule
    mdc_file = next(p for p in paths if "payment" in p.name)
    content = mdc_file.read_text(encoding="utf-8")
    assert "globs: src/pay/**" in content
    assert "No DB I/O in calc" in content


def test_export_claude_md(tmp_path: Path):
    r1 = Rule(
        id="r_p0",
        project_id="proj1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Payment Security Redline",
        content_points=["No DB I/O in calc"],
        status=RuleStatus.ACTIVE
    )
    claude_file = tmp_path / "CLAUDE.md"
    RuleExporter.export_claude_md([r1], out_file=claude_file)

    assert claude_file.exists()
    content = claude_file.read_text(encoding="utf-8")
    assert "## 🏛️ Persistent Architecture Contracts (P0 / Redlines)" in content
    assert "No DB I/O in calc" in content
