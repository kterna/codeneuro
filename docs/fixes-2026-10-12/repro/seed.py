"""Isolated CodeNeuro audit fixtures and behavioral probes; production data is never used."""
from pathlib import Path
import sys, json, asyncio, sqlite3
from datetime import datetime, timedelta, timezone
import httpx

source, run = map(Path, sys.argv[1:3])
sys.path.insert(0, str(source / "src"))
from codeneuro.__main__ import main, create_http_app
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.workflows.product import Product
from codeneuro.modules.workspaces import Actor
from codeneuro.modules.knowledge import Priority, matches
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.tasks import ProductError

db = run / "audit.db"
run.mkdir(parents=True, exist_ok=True)
if db.exists():
    raise SystemExit('Refusing to seed an existing database; choose a new temporary QA directory.')
main(["migrate", "--db", str(db)])
uow = SqliteUnitOfWork(str(db))
product = Product(uow)
human, agent = Actor("web", "human"), Actor("mcp")
fixture = run / "fixture-worktree"
for name in ["README.md", "src/pay/refund.py", "src/payment/charge.py", "src/lib/helper.py",
             "src/lib/client.ts", "src/deep/level3/level4/leaf.py", "tests/test_refund.py"]:
    target = fixture / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# synthetic audit fixture\n", encoding="utf-8")

def project(pid, name):
    return product.workspaces.register_project(human, pid, name)
def task(pid, title, debug=True, workspace=None, machine="audit-host"):
    t = product.workspaces.create_task(agent, pid, title, "用于独立产品审查的合成业务数据")
    se = product.workspaces.start_session(agent, pid, str(workspace or fixture), t.id,
        debug=debug, machine_name=machine, platform="windows", git_branch="audit")
    return t, se
def rule(pid, title, scope=("src/**",), priority=Priority.P1, task_id=None):
    return product.knowledge.create_rule(human, pid, title,
        ("保持幂等，失败时保留原始输入并提供可重试结果。", "准确呈现状态、适用范围和证据来源。"),
        scope, priority, task_id=task_id)

project("audit-a", "结算平台 · 产品审查示例")
project("audit-b", "对照项目 · 独立知识库")
project("audit-empty", "空项目 · 首次使用")
t, session = task("audit-a", "退款幂等与审计")
reqs = [product.requirements.submit_requirement(agent, session.id, text, f"seed-{i}") for i,text in enumerate([
    "退款幂等与审计：同一请求最多退款一次。\n超时必须保留重试凭据，并且展示每次操作的准确结果。",
    "退款幂等与审计：补充跨进程并发验证、状态归档和异常处理。"])]
global_rule=rule("audit-a","全局 P0 · 资金安全",("**",),Priority.P0)
pay_rule=rule("audit-a","仅 pay 模块 · 不应匹配 payment",("src/pay/**",))
py_rule=rule("audit-a","Python 文件约束 · glob 匹配",("src/**/*.py",))
root_rule=rule("audit-a","仅根目录文件 · 单星号",("*",),Priority.P2)
deep_rule=rule("audit-a","深层目录规则",("src/deep/level3/level4/**",),Priority.P2)
temporary=rule("audit-a","当前任务临时约束",("src/**",),task_id=t.id)
b_task,b_session=task("audit-b","对照任务")
rule("audit-b","仅对照工程可见的契约",("**",),Priority.P2)
other,other_session=task("audit-a","日志治理")
rule("audit-a","其他任务独享规则",("src/**",),task_id=other.id)
product.requirements.submit_requirement(agent,other_session.id,"日志治理：为操作补充结构化证据。","other-req")
paused,paused_session=task("audit-a","等待支付网关确认")
product.requirements.submit_requirement(agent,paused_session.id,"等待上游提供退款幂等协议。","pause-req")
fresh=next(x for x in product.workspaces.list_tasks(agent,"audit-a") if x.id==paused.id)
product.workspaces.pause_task(human,"audit-a",paused.id,fresh.revision,"等待上游")
closed,closed_session=task("audit-a","完成历史需求")
closed_req=product.requirements.submit_requirement(agent,closed_session.id,"已完成兼容性验证。","closed-req")
closed_rule=rule("audit-a","随需求完成而停用的规则",("tests/**",),task_id=closed.id)
product.requirements.archive_requirement(agent,closed_session.id,closed_req.id,1,"审查样本：归档结果验证成功。")
empty_task,empty_session=task("audit-a","未提交需求的 MCP 任务")
draft=product.governance.create_task_rule(agent,session.id,"等待证据的草稿",("新规则等待两个成功证据。",),("src/**",),"审查样本")
revoked=product.governance.create_task_rule(agent,session.id,"已主动撤销的规则",("暂不采用。",),("src/**",),"审查样本")
product.governance.mutate_task_rule(agent,session.id,revoked["rule"]["id"],1,"revoke","审查撤销状态")
for i in range(9):
    product.context.record_finding(agent,session.id,"src/pay/**",f"避坑便签 {i+1}：不要在退款超时后丢弃请求标识。仅本任务下发。")
approved=product.knowledge.propose_contract(agent,session.id,global_rule.id,"已批准 · 资金契约修订",
    ("资金变更需要幂等键和完整审计。",),("**",),Priority.P0,"security","明确资金约束")
product.knowledge.review_contract(human,"audit-a",approved.id,True,"批准此修订")
rejected=product.knowledge.propose_contract(agent,session.id,global_rule.id,"已拒绝 · 放宽资金约束",
    ("不采纳此条款。",),("**",),Priority.P2,"business","用于验证拒绝状态")
product.knowledge.review_contract(human,"audit-a",rejected.id,False,"证据不足，拒绝")
pending=[]
for i in range(6):
    pending.append(product.knowledge.propose_contract(agent,session.id,pay_rule.id,f"待审阅方案 {i+1}",
        (f"方案 {i+1}：发生超时时需要保留完整的诊断信息和幂等凭据。",),
        ("src/**",),Priority.P2,"gotcha",f"审查条款、范围、优先级与分类的全部变更 {i+1}"))
delivery=product.context.get_context(agent,session.id,ContextQuery(("src/pay/refund.py",)),"seed-delivery")
product.feedback.rate_rule(agent,session.id,delivery.id,pay_rule.id,5,"核心需要")
issue=product.feedback.report_issue(agent,session.id,"noise","应有人工处理入口的问题","审查问题闭环",
    "src/pay/refund.py",(pay_rule.id,),"审阅后处理")
for i in range(3):
    product.context.get_context(agent,session.id,ContextQuery(("src/pay/refund.py",)),f"extra-delivery-{i}")


with uow.write() as tx:
    for i in range(160):
        tx.audit.record('audit-a', 'qa-human', 'qa.fixture', f'qa-event-{i}', {'index': i})
fixtures = {
    'project': 'audit-a', 'task': t.id, 'other_task': other.id,
    'session': session.id, 'requirements': [r.id for r in reqs],
    'rules': {'global': global_rule.id, 'pay': pay_rule.id, 'python': py_rule.id,
              'root': root_rule.id, 'deep': deep_rule.id},
    'approved': approved.id, 'rejected': rejected.id,
    'pending': [p.id for p in pending], 'empty_task': empty_task.id,
}
(run / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding='utf-8')
uow.dispose()
print('Synthetic repair QA fixtures created at', run)
