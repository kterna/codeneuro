"""Unit tests for Scope Matcher."""

import pytest
from codeneuro.matcher import ScopeMatcher
from codeneuro.models import Lifecycle, Priority, Rule, RuleStatus


@pytest.fixture
def matcher():
    return ScopeMatcher()


def test_glob_matching(matcher: ScopeMatcher):
    assert matcher.matches_pattern("src/pay/**", "src/pay/checkout.ts")
    assert matcher.matches_pattern("src/pay/**", "src/pay/v2/nested/checkout.ts")
    assert not matcher.matches_pattern("src/pay/**", "src/order/checkout.ts")

    assert matcher.matches_pattern("*.py", "test.py")
    assert matcher.matches_pattern("tests/*.py", "tests/test_one.py")
    assert matcher.matches_pattern("src/utils/crypto.ts", "src/utils/crypto.ts")


def test_rule_filtering_and_priority_sort(matcher: ScopeMatcher):
    r_long_p1 = Rule(
        id="r1",
        project_id="p1",
        scope_patterns=["src/services/**"],
        priority=Priority.P1,
        lifecycle=Lifecycle.LONG_TERM,
        title="Service General Convention",
        content_points=["Use DI"],
    )
    r_long_p0 = Rule(
        id="r2",
        project_id="p1",
        scope_patterns=["src/services/pay/**"],
        priority=Priority.P0,
        lifecycle=Lifecycle.LONG_TERM,
        title="Payment Security Redline",
        content_points=["No DB I/O in calc"],
    )
    r_short_active = Rule(
        id="r3",
        project_id="p1",
        task_id="task_1",
        scope_patterns=["src/services/pay/checkout.ts"],
        priority=Priority.P1,
        lifecycle=Lifecycle.SHORT_TERM,
        title="Checkout V2 Parameter",
        content_points=["Add split_tag"],
    )
    r_short_other_task = Rule(
        id="r4",
        project_id="p1",
        task_id="task_2",
        scope_patterns=["src/services/pay/checkout.ts"],
        priority=Priority.P0,
        lifecycle=Lifecycle.SHORT_TERM,
        title="Unrelated Task Rule",
        content_points=["Ignore me"],
    )

    all_rules = [r_long_p1, r_long_p0, r_short_active, r_short_other_task]

    # Filter for task_1 on checkout.ts
    long_term, short_term = matcher.filter_rules(
        all_rules, file_path="src/services/pay/checkout.ts", active_task_id="task_1"
    )

    # Long term should have r2 (P0) before r1 (P1)
    assert len(long_term) == 2
    assert long_term[0].id == "r2"
    assert long_term[1].id == "r1"

    # Short term should only have r3 from task_1, excluding task_2
    assert len(short_term) == 1
    assert short_term[0].id == "r3"
