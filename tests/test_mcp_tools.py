"""Unit tests for MCP Server Tools."""

import pytest
from codeneuro.mcp_server import create_mcp_server
from codeneuro.models import Lifecycle, Priority, Project, Rule, Task
from codeneuro.storage import Storage


@pytest.mark.anyio
async def test_mcp_tools_flow():
    storage = Storage(":memory:")
    server = create_mcp_server(storage)

    # 1. Setup base project and task
    storage.create_project(Project(id="proj_mcp", name="MCP Project"))
    storage.create_task(Task(id="task_001", project_id="proj_mcp", title="Refactor Task"))

    # 2. Add a long-term rule and a short-term rule
    storage.create_rule(
        Rule(
            id="r_long",
            project_id="proj_mcp",
            scope_patterns=["src/core/**"],
            priority=Priority.P0,
            lifecycle=Lifecycle.LONG_TERM,
            title="Core Zero Crash Contract",
            content_points=["All panics must be recovered"],
        )
    )
    storage.create_rule(
        Rule(
            id="r_short",
            project_id="proj_mcp",
            task_id="task_001",
            scope_patterns=["src/core/cache.py"],
            priority=Priority.P1,
            lifecycle=Lifecycle.SHORT_TERM,
            title="Cache Redis TTL parameter",
            content_points=["Set TTL to 60 seconds"],
        )
    )

    # 3. Test codeneuro_get_context tool
    res = await server.call_tool(
        "codeneuro_get_context",
        {
            "file_path": "src/core/cache.py",
            "project_id": "proj_mcp",
            "task_id": "task_001",
        },
    )
    context_out = res.content[0].text
    assert "Core Zero Crash Contract" in context_out
    assert "Cache Redis TTL parameter" in context_out

    # 4. Test codeneuro_record_finding tool
    res = await server.call_tool(
        "codeneuro_record_finding",
        {
            "project_id": "proj_mcp",
            "target_path": "src/core/cache.py",
            "finding_text": "Redis cluster mode requires slot calculation",
            "task_id": "task_001",
            "suggested_priority": "P1",
        },
    )
    record_out = res.content[0].text
    assert "Successfully recorded finding" in record_out

    # 5. Query context again to verify the finding appears
    res = await server.call_tool(
        "codeneuro_get_context",
        {
            "file_path": "src/core/cache.py",
            "project_id": "proj_mcp",
            "task_id": "task_001",
        },
    )
    context_out2 = res.content[0].text
    assert "Redis cluster mode requires slot calculation" in context_out2

    # 6. Test codeneuro_patch_rule tool (revoke short term)
    res = await server.call_tool(
        "codeneuro_patch_rule",
        {
            "rule_id": "r_short",
            "action": "revoke",
            "reason": "No longer using Redis cache",
        },
    )
    patch_out = res.content[0].text
    assert "successfully revoked" in patch_out

    # 7. Test codeneuro_propose_contract tool
    res = await server.call_tool(
        "codeneuro_propose_contract",
        {
            "project_id": "proj_mcp",
            "target_component": "src/core/cache.py",
            "proposed_contract": "All cache operations must use InMemoryLRU",
            "justification": "Deprecated remote redis",
        },
    )
    prop_out = res.content[0].text
    assert "submitted for component" in prop_out
