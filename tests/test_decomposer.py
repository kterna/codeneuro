"""Unit tests for Requirement Decomposer."""

from codeneuro.decomposer import Decomposer
from codeneuro.models import Priority


def test_heuristic_decomposer():
    decomposer = Decomposer()
    text = """
    # 优惠券结算服务升级
    1. 涉及路径 src/services/coupon/** 与 src/controllers/order.ts
    2. 禁止在拆分计算中出现除零错误 (P0核心安全红线)
    3. 支持新字段 `can_stack_with_points` 并向下兼容
    4. 建议在结算日志中打印计算耗时
    """

    rules = decomposer.heuristic_decompose(
        project_id="p_test",
        task_id="task_coupon",
        text=text,
    )

    assert len(rules) >= 1
    # Check that paths were recognized
    all_scopes = []
    for r in rules:
        all_scopes.extend(r.scope_patterns)

    assert any("src/services/coupon" in s for s in all_scopes)
    # Check that P0 was detected from the "禁止" keyword
    assert any(r.priority == Priority.P0 for r in rules)
