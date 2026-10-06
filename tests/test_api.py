"""Integration tests for FastAPI REST endpoints and WebUI serving."""

import pytest
from fastapi.testclient import TestClient

from codeneuro.api import create_app
from codeneuro.storage import Storage


@pytest.fixture
def client():
    storage = Storage(":memory:")
    app = create_app(storage=storage)
    return TestClient(app)


def test_full_api_workflow(client: TestClient):
    # 1. Create Project
    res = client.post("/api/projects", json={"name": "Test Core Project", "description": "Test Desc"})
    assert res.status_code == 200
    p = res.json()
    project_id = p["id"]

    # 2. Decompose a Requirement into Scoped Rules
    prd_text = """
    # 支付结算重构
    - 涉及路径 src/services/pay/** 与 src/api/pay.py
    - 严禁在日志中输出未脱敏的银行卡号 (P0安全红线)
    - 增加 split_tag 参数
    """
    res = client.post(
        f"/api/projects/{project_id}/decompose",
        json={"task_id": "TASK-PAY-V2", "text": prd_text},
    )
    assert res.status_code == 200
    rules = res.json()
    assert len(rules) > 0
    rule_id = rules[0]["id"]

    # 3. Query Global Stats
    res_stats = client.get("/api/stats")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_projects"] == 1
    assert stats["active_rules"] > 0
    assert stats["p0_count"] > 0

    # 4. Query Cognitive Tree
    res_tree = client.get(f"/api/projects/{project_id}/tree")
    assert res_tree.status_code == 200
    tree_data = res_tree.json()["tree"]
    assert tree_data["name"] == "Test Core Project"
    assert len(tree_data["children"]) > 0

    # 5. Query Heatmap
    res = client.get(f"/api/projects/{project_id}/heatmap")
    assert res.status_code == 200
    heatmap_data = res.json()["heatmap"]
    assert len(heatmap_data) > 0
    assert any(item["p0_count"] > 0 for item in heatmap_data)

    # 6. Resolve Context for a matching file
    res = client.get(f"/api/context?project_id={project_id}&file_path=src/services/pay/checkout.ts&task_id=TASK-PAY-V2")
    assert res.status_code == 200
    context_data = res.json()
    assert "src/services/pay/checkout.ts" in context_data["rendered_markdown"]
    assert "严禁在日志中输出未脱敏的银行卡号" in context_data["rendered_markdown"]

    # 7. Test Export API
    res_export = client.post(f"/api/projects/{project_id}/export", json={"format": "cursor", "out_dir": "/tmp/test_export"})
    assert res_export.status_code == 200
    export_data = res_export.json()
    assert export_data["files_count"] > 0

    # 8. Delete Rule API
    del_res = client.delete(f"/api/rules/{rule_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_rule_id"] == rule_id

    # 9. Check WebUI index response
    res_ui = client.get("/")
    assert res_ui.status_code == 200
    assert "CodeNeuro" in res_ui.text
    assert "代码认知拓扑树" in res_ui.text
