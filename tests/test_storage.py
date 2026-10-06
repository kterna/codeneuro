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
