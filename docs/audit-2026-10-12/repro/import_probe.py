from pathlib import Path
import sys,json,subprocess,sqlite3
source,run=map(Path,sys.argv[1:3])
sys.path.insert(0,str(source/'src'))
from codeneuro.__main__ import main
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.workflows.product import Product
from codeneuro.modules.workspaces import Actor
from codeneuro.modules.context import ContextQuery
case=run/'import-case';case.mkdir()
(case/'dist_batches').mkdir()
db=case/'new.db';main(['migrate','--db',str(db)])
fixture={"projects":[{"id":"import-a","name":"Import A"},{"id":"import-b","name":"Import B"}],
"tasks":[{"id":"task-a","project_id":"import-a","title":"imported A"},{"id":"task-b","project_id":"import-b","title":"imported B"},
         {"id":"task-unknown","project_id":"not-a-project","title":"unknown owner"}],
"rules":[{"project_id":"import-a","task_id":"task-a","title":"imported rule","points":["preserve scope"],"patterns":["src/**"]}]}
(case/'dist_batches/result_batch_1.json').write_text(json.dumps(fixture),encoding='utf-8')
proc=subprocess.run([sys.executable,'-B',str(source/'scripts/load_batches_into_codeneuro.py'),str(db)],cwd=case,capture_output=True,text=True,encoding='utf-8',errors='replace')
out={"import_exit":proc.returncode,"import_stdout":proc.stdout,"import_stderr":proc.stderr}
if proc.returncode==0:
    with sqlite3.connect(db) as c:
        out["snapshots"]={table:c.execute("select count(*) from "+table).fetchone()[0] for table in ['rules','rule_versions','requirements','requirement_versions','audit']}
        out["unknown_project_task_owner"]=c.execute("select project_id from tasks where id='task-unknown'").fetchone()[0]
        out["integrity"]=c.execute("pragma integrity_check").fetchone()[0]
    uow=SqliteUnitOfWork(str(db));product=Product(uow);actor=Actor('mcp')
    session=product.workspaces.start_session(actor,'import-a',str(case),'task-a')
    try:
        result=product.context.get_context(actor,session.id,ContextQuery(('src/file.py',)))
        out["context"]={"ok":True,"delivery":result.id}
    except Exception as e:out["context"]={"ok":False,"error_type":type(e).__name__,"error":str(e)}
    uow.dispose()
(run/'import-results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))

