"""Unit tests for storage operations."""

import pytest
from codeneuro.models import (
    Finding,
    FindingStatus,
    Lifecycle,
    Priority,
    Project,
    Proposal,
    Rule,
    RuleStatus,
    Task,
    TaskStatus,
)
from codeneuro.storage import Storage


@pytest.fixture
def storage():
    return Storage(":memory:")


def test_project_crud(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core", root_paths=["src/"])
    storage.create_project(p)

    fetched = storage.get_project("p1")
    assert fetched is not None
    assert fetched.name == "Ecommerce Core"
    assert fetched.root_paths == ["src/"]

    all_p = storage.list_projects()
    assert len(all_p) == 1


def test_task_lifecycle(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core")
    storage.create_project(p)

    t = Task(id="t1", project_id="p1", title="Payment Gateway Upgrade", status=TaskStatus.ACTIVE)
    storage.create_task(t)

    fetched = storage.get_task("t1")
    assert fetched is not None
    assert fetched.status == TaskStatus.ACTIVE

    storage.update_task_status("t1", TaskStatus.RELEASED)
    assert storage.get_task("t1").status == TaskStatus.RELEASED


def test_rule_crud_and_hits(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core")
    storage.create_project(p)

    r = Rule(
        id="r1",
        project_id="p1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Payment Security Contract",
        content_points=["No plain text credentials"],
        status=RuleStatus.ACTIVE,
    )
    storage.create_rule(r)

    active_rules = storage.list_rules("p1", status=RuleStatus.ACTIVE)
    assert len(active_rules) == 1
    assert active_rules[0].priority == Priority.P0

    storage.increment_rule_hits(["r1"])
    updated_r = storage.get_rule("r1")
    assert updated_r.hit_count == 1
    assert updated_r.last_hit_at is not None


def test_findings_and_proposals(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core")
    storage.create_project(p)

    f = Finding(
        id="f1",
        project_id="p1",
        target_path="src/pay/calc.ts",
        finding_text="Floating point precision issue with currency",
        suggested_priority=Priority.P0,
        status=FindingStatus.PENDING_REVIEW,
    )
    storage.create_finding(f)
    assert len(storage.list_findings("p1", FindingStatus.PENDING_REVIEW)) == 1

    storage.update_finding_status("f1", FindingStatus.CRYSTALLIZED)
    assert len(storage.list_findings("p1", FindingStatus.PENDING_REVIEW)) == 0

    prop = Proposal(
        id="prop1",
        project_id="p1",
        target_component="src/pay/gateway.ts",
        proposed_contract="Use OAuth v2 exclusively",
        justification="Deprecated legacy basic auth",
        status="pending",
    )
    storage.create_proposal(prop)
    assert len(storage.list_proposals("p1", "pending")) == 1


def test_rule_versioning_and_rollback(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core")
    storage.create_project(p)

    r = Rule(
        id="r1",
        project_id="p1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Payment Security Contract v1",
        content_points=["Point 1"],
        status=RuleStatus.ACTIVE,
    )
    storage.create_rule(r)

    # Initial version 1 snapshot
    versions = storage.list_rule_versions("r1")
    assert len(versions) == 1
    assert versions[0].version_number == 1

    # Update to version 2
    storage.update_rule_content(
        rule_id="r1",
        title="Payment Security Contract v2",
        content_points=["Point 1", "Point 2 updated"],
        scope_patterns=["src/pay/**", "src/checkout/**"],
        priority=Priority.P0,
        change_summary="Add Point 2",
        operator="developer"
    )

    r_v2 = storage.get_rule("r1")
    assert r_v2.version == 2
    assert "Point 2 updated" in r_v2.content_points

    versions_v2 = storage.list_rule_versions("r1")
    assert len(versions_v2) == 2

    # Rollback to version 1
    r_rolled = storage.rollback_rule_version("r1", target_version=1)
    assert r_rolled is not None
    assert r_rolled.title == "Payment Security Contract v1"
    assert r_rolled.content_points == ["Point 1"]
    assert r_rolled.version == 3 # Snapshot of rollback commit


def test_health_check_and_conflict_engine(storage: Storage):
    p = Project(id="p1", name="Ecommerce Core")
    storage.create_project(p)

    # Rule 1
    r1 = Rule(
        id="r1",
        project_id="p1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Rule 1",
        content_points=["No Float"],
    )
    # Rule 2 with opposing priority on same scope
    r2 = Rule(
        id="r2",
        project_id="p1",
        scope_patterns=["src/pay/**"],
        priority=Priority.P1,
        lifecycle=Lifecycle.LONG_TERM,
        title="Rule 2",
        content_points=["Allow Float"],
    )
    storage.create_rule(r1)
    baseline = storage.check_project_health("p1").overall_score
    storage.create_rule(r2)

    report = storage.check_project_health("p1")
    assert report.total_rules == 2
    assert len(report.conflicts) >= 1
    assert any(c.conflict_type == "scope_overlap" for c in report.conflicts)
    assert report.overall_score == baseline  # Different priorities are legitimate, not a failure.
