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
    assert 'globs: "src/pay/**"' in content
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
    assert "codeneuro:start" in content
    assert "No DB I/O in calc" in content


def test_export_never_leaks_other_tasks_and_removes_only_owned_files(tmp_path):
    from codeneuro.models import Task
    long=Rule(id='long',project_id='p',title='global',lifecycle=Lifecycle.LONG_TERM,priority=Priority.P0,content_points=['global'])
    a=Rule(id='a',project_id='p',task_id='a',title='task A',priority=Priority.P0,content_points=['a'])
    b=Rule(id='b',project_id='p',task_id='b',title='task B',priority=Priority.P0,content_points=['b'])
    first=RuleExporter.export_cursor_rules([long,a,b],tmp_path,'a')
    assert len(first)==2
    human=tmp_path/'.cursor/rules/human.mdc';human.write_text('keep')
    second=RuleExporter.export_cursor_rules([long,a,b],tmp_path,'b')
    assert len(second)==2
    assert human.read_text()=='keep'
    assert len(list((tmp_path/'.cursor/rules').glob('codeneuro-*.mdc')))==2
    assert not next(p for p in first if 'task-a' in p.name).exists()
    instructions=tmp_path/'CLAUDE.md';instructions.write_text('# Human instructions\nKEEP ME\n')
    RuleExporter.export_claude_md([long,a,b],instructions,'a')
    data=instructions.read_text();assert 'KEEP ME' in data and 'task A' in data and 'task B' not in data
    RuleExporter.export_claude_md([long,a,b],instructions,'b')
    data=instructions.read_text();assert data.count('codeneuro:start')==1 and 'task A' not in data and 'task B' in data


def test_export_cannot_escape_through_symlinks(tmp_path):
    from codeneuro.database import DomainError
    outside=tmp_path/'outside';outside.mkdir()
    workspace=tmp_path/'workspace';workspace.mkdir()
    (workspace/'.cursor').symlink_to(outside,target_is_directory=True)
    with pytest.raises(DomainError):RuleExporter.export_cursor_rules([],workspace)
