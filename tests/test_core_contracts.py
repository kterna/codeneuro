"""Acceptance contracts for real sessions, isolation, lifecycle and durable evidence."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import pytest
from codeneuro.database import Conflict, DomainError
from codeneuro.models import Project, Task, TaskStatus, Rule, Lifecycle, Priority, RuleStatus
from codeneuro.service import ContextService
from codeneuro.storage import Storage


@pytest.fixture
def core(tmp_path):
    root_a, root_b = tmp_path/'a', tmp_path/'b'
    root_a.mkdir(); root_b.mkdir()
    store = Storage(str(tmp_path/'state.db'))
    store.create_project(Project(id='p', name='project', root_paths=[str(root_a), str(root_b)]))
    store.create_project(Project(id='q', name='other', root_paths=[str(root_b)]))
    for tid, project in [('a','p'),('b','p'),('qtask','q')]:
        store.create_task(Task(id=tid, project_id=project, title=tid))
    for rid, task, priority in [('global',None,Priority.P0),('ra','a',Priority.P1),('rb','b',Priority.P1)]:
        store.create_rule(Rule(id=rid,project_id='p',task_id=task,priority=priority,
            lifecycle=Lifecycle.SHORT_TERM if task else Lifecycle.LONG_TERM,
            title=rid,scope_patterns=['src/**'],content_points=[rid+' complete instruction']))
    service = ContextService(store)
    a = service.start_session('p',str(root_a),'a',debug=True)['id']
    b = service.start_session('p',str(root_b),'b',debug=True)['id']
    yield store,service,a,b,root_a,root_b
    store.close()


def test_workspace_task_isolation_and_readonly_preview(core):
    store,svc,a,b,_,_=core
    for sid,expected,excluded in [(a,'ra','rb'),(b,'rb','ra')]:
        result=svc.resolve(session_id=sid,file_path='src/example.py')
        assert expected+' complete instruction' in result.rendered_markdown
        assert excluded+' complete instruction' not in result.rendered_markdown
    before=store.get_rule('global').hit_count
    svc.resolve(project_id='p',task_id='a',file_path='src/example.py')
    assert store.get_rule('global').hit_count==before
    with pytest.raises(DomainError):svc.resolve(session_id=a,project_id='q',file_path='src/a.py')
    with pytest.raises(DomainError):svc.resolve(session_id=a,task_id='b',file_path='src/a.py')
    with pytest.raises(DomainError):svc.start_session('p',str(core[4]),'qtask')


def test_archive_task_atomically_expires_rules_and_keeps_contracts(core):
    store,svc,a,_,_,_=core
    before=svc.resolve(session_id=a,file_path='src/a.py')
    assert before.short_term_rules
    store.update_task_status('a',TaskStatus.ARCHIVED)
    after=svc.resolve(session_id=a,file_path='src/a.py')
    assert not after.short_term_rules
    assert [r.id for r in after.long_term_rules]==['global']
    assert store.get_rule('ra').status==RuleStatus.DEPRECATED
    assert store.list_rule_versions('ra')[0].status==RuleStatus.DEPRECATED
    with pytest.raises(Conflict):store.rollback_rule_version('ra',1)
    assert store.get_rule('ra').status==RuleStatus.DEPRECATED


def test_feedback_is_session_and_version_scoped_and_p0_stays_visible(core):
    store,svc,a,_,root,_=core
    receipt=svc.resolve(session_id=a,file_path='src/a.py')
    for rid in ['ra','global']:
        result=svc.evaluate(session_id=a,delivery_id=receipt.delivery_id,rule_id=rid,score=0)
        again=svc.evaluate(session_id=a,delivery_id=receipt.delivery_id,rule_id=rid,score=0)
        assert again['duplicate']
        assert store.get_rule(rid).eval_count==1
    reduced=svc.resolve(session_id=a,file_path='src/a.py')
    assert 'ra complete instruction' not in reduced.rendered_markdown
    assert 'global complete instruction' in reduced.rendered_markdown
    other=svc.start_session('p',str(root),'a',debug=True)['id']
    assert 'ra complete instruction' in svc.resolve(session_id=other,file_path='src/a.py').rendered_markdown
    store.update_rule_content('ra','ra',['new instruction'],['src/**'],Priority.P1,expected_version=1)
    assert store.get_rule('ra').eval_count==0  # Feedback belongs to the version actually seen.
    assert 'new instruction' in svc.resolve(session_id=a,file_path='src/a.py').rendered_markdown
    with pytest.raises(DomainError):svc.evaluate(session_id=other,delivery_id=receipt.delivery_id,rule_id='ra',score=5)
    with pytest.raises(DomainError):svc.evaluate(session_id=a,delivery_id=receipt.delivery_id,rule_id='rb',score=5)
    with pytest.raises(Conflict):svc.evaluate(session_id=a,delivery_id=receipt.delivery_id,rule_id='ra',score=5)


def test_unsafe_paths_and_cross_project_rule_relations_rejected(core,tmp_path):
    store,svc,a,_,root,_=core
    (root/'outside').symlink_to(tmp_path)
    for path in ['../private','/etc/passwd','src/../../private','outside/private']:
        with pytest.raises(DomainError):svc.resolve(session_id=a,file_path=path)
    with pytest.raises(DomainError):
        store.create_rule(Rule(id='wrong',project_id='p',task_id='qtask',title='bad',content_points=['x']))
    assert store.get_rule('wrong') is None


def test_rule_snapshot_and_audit_roll_back_together(core):
    store,_,_,_,_,_=core
    store.conn.execute("CREATE TRIGGER fail_version BEFORE INSERT ON rule_versions WHEN NEW.version_number=2 BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    before=store.conn.execute('SELECT count(*) FROM audit_events').fetchone()[0]
    with pytest.raises(sqlite3.IntegrityError):
        store.update_rule_content('ra','new',['changed'],['src/**'],Priority.P1)
    assert store.get_rule('ra').version==1
    assert store.get_rule('ra').title=='ra'
    assert len(store.list_rule_versions('ra'))==1
    assert store.conn.execute('SELECT count(*) FROM audit_events').fetchone()[0]==before


def test_concurrent_process_connections_do_not_lose_edits_or_double_count(core):
    store,svc,a,_,_,_=core
    other=Storage(store.db_path)
    barrier=threading.Barrier(2)
    def update(db):
        barrier.wait()
        try:
            db.update_rule_content('ra','changed',['new'],['src/**'],Priority.P1,expected_version=1)
            return 'updated'
        except Conflict:return 'conflict'
    with ThreadPoolExecutor(2) as pool:
        outcomes=list(pool.map(update,[store,other]))
    assert sorted(outcomes)==['conflict','updated']
    barrier.reset()
    def deliver(db):
        barrier.wait()
        return ContextService(db).resolve(session_id=a,file_path='src/a.py',request_id='same-request').delivery_id
    with ThreadPoolExecutor(2) as pool:ids=list(pool.map(deliver,[store,other]))
    assert ids[0]==ids[1]
    assert store.get_rule('ra').hit_count==1
    other.close()


def test_restart_preserves_receipts_feedback_and_versions(core):
    store,svc,a,_,_,_=core
    receipt=svc.resolve(session_id=a,file_path='src/a.py',request_id='retry')
    svc.evaluate(session_id=a,delivery_id=receipt.delivery_id,rule_id='ra',score=0)
    another=Storage(store.db_path)
    new=ContextService(another)
    assert new.resolve(session_id=a,file_path='src/a.py',request_id='retry').delivery_id==receipt.delivery_id
    assert 'ra complete instruction' not in new.resolve(session_id=a,file_path='src/a.py').rendered_markdown
    assert another.conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    assert list(another.conn.execute('PRAGMA foreign_key_check'))==[]
    another.close()


def test_context_budget_never_silently_drops_p0(core):
    store,svc,a,_,_,_=core
    store.update_rule_content('global','must keep',['IMPORTANT'*300],['src/**'],Priority.P0)
    result=svc.resolve(session_id=a,file_path='src/a.py',max_chars=512)
    assert result.budget_exceeded
    assert 'IMPORTANT'*300 in result.rendered_markdown
    assert result.omitted_rules


def test_session_close_and_debug_gate(core):
    store,svc,a,_,root,_=core
    plain=svc.start_session('p',str(root),'a',debug=False)['id']
    receipt=svc.resolve(session_id=plain,file_path='src/a.py')
    with pytest.raises(DomainError):svc.evaluate(session_id=plain,delivery_id=receipt.delivery_id,rule_id='ra',score=0)
    svc.close_session(a)
    with pytest.raises(Conflict):svc.resolve(session_id=a,file_path='src/a.py')


def test_findings_from_other_tasks_are_not_injected(core):
    _,svc,a,b,_,_=core
    svc.record_finding(a,'src/a.py','only for task a')
    assert 'only for task a' in svc.resolve(session_id=a,file_path='src/a.py').rendered_markdown
    assert 'only for task a' not in svc.resolve(session_id=b,file_path='src/a.py').rendered_markdown


def test_actual_git_worktree_accepted_but_nested_directory_rejected(tmp_path):
    import subprocess
    repo=tmp_path/'repo';repo.mkdir()
    def git(*args):subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True)
    git('init')
    git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--allow-empty','-m','fixture')
    worktree=tmp_path/'worktree';git('worktree','add','-b','task-branch',str(worktree))
    nested=worktree/'src';nested.mkdir()
    store=Storage(':memory:')
    store.create_project(Project(id='p',name='repo',root_paths=[str(repo)]))
    service=ContextService(store)
    assert service.start_session('p',str(worktree))['worktree_id']
    with pytest.raises(DomainError):service.start_session('p',str(nested))
    store.close()


def test_mutated_candidate_cannot_bypass_path_validation(core):
    store,_,_,_,_,_=core
    candidate=Rule(id='candidate',project_id='p',task_id='a',title='candidate',content_points=['rule'],status=RuleStatus.DRAFT)
    candidate.scope_patterns=['/outside/file.py']
    with pytest.raises(DomainError):store.create_rule(candidate)
    assert store.get_rule('candidate') is None
