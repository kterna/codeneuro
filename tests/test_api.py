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

    # 3. Query Heatmap
    res = client.get(f"/api/projects/{project_id}/heatmap")
    assert res.status_code == 200
    heatmap_data = res.json()["heatmap"]
    assert len(heatmap_data) > 0
    assert any(item["p0_count"] > 0 for item in heatmap_data)

    # 4. Resolve Context for a matching file
    res = client.get(f"/api/context?project_id={project_id}&file_path=src/services/pay/checkout.ts&task_id=TASK-PAY-V2")
    assert res.status_code == 200
    context_data = res.json()
    assert "src/services/pay/checkout.ts" in context_data["rendered_markdown"]
    assert "严禁在日志中输出未脱敏的银行卡号" in context_data["rendered_markdown"]

    # 5. Record Finding and Crystallize it
    # First create a finding manually or via API
    # Create rule proposal & approve
    # Check WebUI index response
    res = client.get("/")
    assert res.status_code == 200
    assert "CodeNeuro" in res.text
