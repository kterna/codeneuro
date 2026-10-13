"""Focused regression tests for batch importer ownership, state, and boundary invariants."""

import json
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

import codeneuro
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.adapters.sqlite.schema import (
    projects, tasks, requirements, requirement_versions,
    rules, rule_versions, worktrees, sessions, findings, audit,
    requirement_rule_links
)
from codeneuro.modules.context import ContextQuery
from codeneuro.modules.workspaces import Actor
from codeneuro.workflows.product import Product
from scripts.load_batches_into_codeneuro import (
    load_and_validate, ingest_batches,
    worktree_id_for, project_session_id_for, task_session_id_for
)


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_migrated.db"
    config = Config()
    config.set_main_option(
        'script_location',
        str(Path(codeneuro.__file__).resolve().parent / 'migrations')
    )
    config.set_main_option('codeneuro_db', str(db_file))
    command.upgrade(config, 'head')
    return str(db_file)


def _write_batch(tmp_path: Path, filename: str, data: dict) -> str:
    path = tmp_path / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def test_cross_project_duplicate_task_id_rejected(tmp_path):
    """Reject duplicate task IDs across different projects with source location."""
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [{"id": "proj-a", "name": "Project A"}],
        "tasks": [{"id": "task-dup", "project_id": "proj-a", "title": "Task In A", "status": "active"}]
    })
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "proj-b", "name": "Project B"}],
        "tasks": [{"id": "task-dup", "project_id": "proj-b", "title": "Task In B", "status": "active"}]
    })

    with pytest.raises(ValueError) as exc:
        load_and_validate([b1, b2])

    err = str(exc.value)
    assert "cross-project duplicate ID" in err
    assert "task-dup" in err
    assert "proj-a" in err
    assert "proj-b" in err


def test_cross_task_and_cross_project_requirement_link_rejected(tmp_path):
    """Reject rules linking requirements belonging to a different project or task."""
    # 1. Cross-project requirement link
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [
            {"id": "proj-a", "name": "Project A"},
            {"id": "proj-b", "name": "Project B"}
        ],
        "tasks": [
            {
                "id": "task-a",
                "project_id": "proj-a",
                "title": "Task A",
                "status": "active",
                "requirements": [{"id": "req-a1", "text": "Req A1", "status": "active"}]
            },
            {
                "id": "task-b",
                "project_id": "proj-b",
                "title": "Task B",
                "status": "active"
            }
        ],
        "rules": [
            {
                "id": "rule-cross-proj",
                "project_id": "proj-b",
                "task_id": "task-b",
                "title": "Cross Project Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "requirement_id": "req-a1"
            }
        ]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1])
    assert "links requirement 'req-a1' of project 'proj-a'" in str(exc.value)

    # 2. Cross-task requirement link in same project
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "proj-a", "name": "Project A"}],
        "tasks": [
            {
                "id": "task-a1",
                "project_id": "proj-a",
                "title": "Task A1",
                "status": "active",
                "requirements": [{"id": "req-a1", "text": "Req A1", "status": "active"}]
            },
            {
                "id": "task-a2",
                "project_id": "proj-a",
                "title": "Task A2",
                "status": "active"
            }
        ],
        "rules": [
            {
                "id": "rule-cross-task",
                "project_id": "proj-a",
                "task_id": "task-a2",
                "title": "Cross Task Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "requirement_id": "req-a1"
            }
        ]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2])
    assert "links requirement 'req-a1' of task 'task-a1', but rule belongs to task 'task-a2'" in str(exc.value)

    # 3. Project-level rule linking task-specific requirement
    b3 = _write_batch(tmp_path, "b3.json", {
        "projects": [{"id": "proj-a", "name": "Project A"}],
        "tasks": [
            {
                "id": "task-a1",
                "project_id": "proj-a",
                "title": "Task A1",
                "status": "active",
                "requirements": [{"id": "req-a1", "text": "Req A1", "status": "active"}]
            }
        ],
        "rules": [
            {
                "id": "rule-proj-level",
                "project_id": "proj-a",
                "title": "Project Level Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "requirement_id": "req-a1"
            }
        ]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b3])
    assert "project-level rule cannot link task-specific requirement" in str(exc.value)


def test_live_rule_cannot_link_archived_requirement_or_inactive_task(tmp_path):
    """Live rules cannot reference archived requirements or inactive tasks."""
    # 1. Live rule referencing archived requirement
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [{"id": "proj-a", "name": "Project A"}],
        "tasks": [
            {
                "id": "task-a",
                "project_id": "proj-a",
                "title": "Task A",
                "status": "active",
                "requirements": [{"id": "req-archived", "text": "Done", "status": "archived", "summary": "Finished"}]
            }
        ],
        "rules": [
            {
                "id": "rule-live",
                "project_id": "proj-a",
                "task_id": "task-a",
                "title": "Active Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "status": "active",
                "requirement_id": "req-archived"
            }
        ]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1])
    assert "live rule cannot link archived requirement" in str(exc.value)

    # 2. Live rule referencing inactive task
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "proj-a", "name": "Project A"}],
        "tasks": [
            {
                "id": "task-archived",
                "project_id": "proj-a",
                "title": "Archived Task",
                "status": "archived"
            }
        ],
        "rules": [
            {
                "id": "rule-live-inactive",
                "project_id": "proj-a",
                "task_id": "task-archived",
                "title": "Live Rule On Inactive Task",
                "points": ["P"],
                "patterns": ["src/**"],
                "status": "active"
            }
        ]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2])
    assert "live rule cannot reference inactive task" in str(exc.value)


def test_multi_file_forward_references_import_cleanly(tmp_path, temp_db):
    """File 1 references Task in File 2; two-pass import succeeds atomically."""
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [{"id": "proj-f", "name": "Forward Project"}],
        "rules": [
            {
                "id": "rule-fwd",
                "project_id": "proj-f",
                "task_id": "task-f2",
                "title": "Forward Referencing Rule",
                "points": ["Rule point"],
                "patterns": ["src/**"],
                "requirement_id": "req-f2"
            }
        ],
        "findings": [
            {
                "id": "find-fwd",
                "project_id": "proj-f",
                "task_id": "task-f2",
                "text": "Forward finding",
                "target_path": "src/module.py"
            }
        ]
    })
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "proj-f", "name": "Forward Project"}],
        "tasks": [
            {
                "id": "task-f2",
                "project_id": "proj-f",
                "title": "Task Declared Later",
                "status": "active",
                "requirements": [
                    {"id": "req-f2", "text": "Req Declared Later", "status": "active"}
                ]
            }
        ]
    })

    validated = load_and_validate([b1, b2])

    # Dry-run passes and writes nothing
    ingest_batches(validated, temp_db, dry_run=True)
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            assert len(tx.workspaces.list_projects()) == 0
    finally:
        uow.dispose()

    # Real import succeeds without FK constraint violations
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            projs = tx.workspaces.list_projects()
            assert len(projs) == 1
            assert projs[0]['id'] == 'proj-f'

            task = tx.workspaces.get_task('task-f2', 'proj-f')
            assert task is not None
            assert task.title == 'Task Declared Later'

            req = tx.requirements.get_requirement('req-f2', 'task-f2')
            assert req is not None
            assert req.text == 'Req Declared Later'

            rule = tx.knowledge.get_rule('rule-fwd')
            assert rule is not None
            assert rule.task_id == 'task-f2'

            linked = tx.requirements.linked_requirement('rule-fwd')
            assert linked is not None
            assert linked.id == 'req-f2'

            findings_list = tx.context.pending_findings('proj-f', 'task-f2')
            assert len(findings_list) == 1
            assert findings_list[0].id == 'find-fwd'
            sess = tx.workspaces.get_session(findings_list[0].session_id)
            assert sess is not None
            assert sess.task_id == 'task-f2'
    finally:
        uow.dispose()


def test_live_import_existing_target_task_collision_fails_and_preserves_db(tmp_path, temp_db):
    """Critical D32 test: Live import fails on conflicting existing task and rolls back completely."""
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.write() as tx:
            tx.workspaces.create_project('proj-a', 'Project A')
            tx.workspaces.create_task(
                codeneuro.modules.tasks.Task(
                    id='task-shared',
                    project_id='proj-a',
                    title='Task belonging to A',
                    description='Original',
                    status=codeneuro.modules.tasks.TaskStatus.ACTIVE,
                    revision=1
                )
            )
            tx.audit.record('proj-a', 'seed-actor', 'task.created', 'task-shared', {})
    finally:
        uow.dispose()

    b = _write_batch(tmp_path, "b_conflict.json", {
        "projects": [{"id": "proj-b", "name": "Project B"}],
        "tasks": [{"id": "task-shared", "project_id": "proj-b", "title": "Stolen Task", "status": "active"}]
    })
    validated = load_and_validate([b])

    with pytest.raises(ValueError) as exc:
        ingest_batches(validated, temp_db, dry_run=False)

    assert "Target DB conflict" in str(exc.value)
    assert "task-shared" in str(exc.value)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            p_ids = [p['id'] for p in tx.workspaces.list_projects()]
            assert 'proj-b' not in p_ids
            assert 'proj-a' in p_ids
            t = tx.workspaces.get_task('task-shared', 'proj-a')
            assert t.title == 'Task belonging to A'
            assert t.project_id == 'proj-a'
            audit_records = tx.audit.project_audit('proj-a')
            assert len(audit_records) == 1
    finally:
        uow.dispose()


def test_in_batch_duplicate_field_mismatches_fail(tmp_path):
    """Reject in-batch duplicate identities when semantic fields differ."""
    # 1. Project field mismatch: different branch
    b1a = _write_batch(tmp_path, "b1a.json", {"projects": [{"id": "p1", "name": "P1", "git_branch": "main"}]})
    b1b = _write_batch(tmp_path, "b1b.json", {"projects": [{"id": "p1", "name": "P1", "git_branch": "feature"}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1a, b1b])
    assert "conflicting duplicate declaration" in str(exc.value)

    # 2. Task field mismatch: different description
    b2a = _write_batch(tmp_path, "b2a.json", {"projects": [{"id": "p2", "name": "P2"}], "tasks": [{"id": "t2", "project_id": "p2", "title": "T", "description": "Desc A"}]})
    b2b = _write_batch(tmp_path, "b2b.json", {"projects": [{"id": "p2", "name": "P2"}], "tasks": [{"id": "t2", "project_id": "p2", "title": "T", "description": "Desc B"}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2a, b2b])
    assert "conflicting duplicate declaration" in str(exc.value)

    # 3. Requirement field mismatch: different summary
    b3a = _write_batch(tmp_path, "b3a.json", {"projects": [{"id": "p3", "name": "P3"}], "tasks": [{"id": "t3", "project_id": "p3", "title": "T", "requirements": [{"id": "r3", "text": "Req", "status": "active", "summary": "Sum A"}]}]})
    b3b = _write_batch(tmp_path, "b3b.json", {"projects": [{"id": "p3", "name": "P3"}], "tasks": [{"id": "t3", "project_id": "p3", "title": "T", "requirements": [{"id": "r3", "text": "Req", "status": "active", "summary": "Sum B"}]}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b3a, b3b])
    assert "conflicting duplicate declaration" in str(exc.value)

    # 4. Rule field mismatch: different patterns
    b4a = _write_batch(tmp_path, "b4a.json", {"projects": [{"id": "p4", "name": "P4"}], "rules": [{"id": "r4", "project_id": "p4", "title": "R", "points": ["P"], "patterns": ["src/**"]}]})
    b4b = _write_batch(tmp_path, "b4b.json", {"projects": [{"id": "p4", "name": "P4"}], "rules": [{"id": "r4", "project_id": "p4", "title": "R", "points": ["P"], "patterns": ["pkg/**"]}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b4a, b4b])
    assert "conflicting duplicate rule declaration" in str(exc.value)

    # 5. Finding field mismatch: different priority
    b5a = _write_batch(tmp_path, "b5a.json", {"projects": [{"id": "p5", "name": "P5"}], "tasks": [{"id": "t5", "project_id": "p5", "title": "T"}], "findings": [{"id": "f5", "project_id": "p5", "task_id": "t5", "text": "F", "target_path": "src/a.py", "priority": "P1"}]})
    b5b = _write_batch(tmp_path, "b5b.json", {"projects": [{"id": "p5", "name": "P5"}], "tasks": [{"id": "t5", "project_id": "p5", "title": "T"}], "findings": [{"id": "f5", "project_id": "p5", "task_id": "t5", "text": "F", "target_path": "src/a.py", "priority": "P2"}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b5a, b5b])
    assert "conflicting duplicate finding declaration" in str(exc.value)


def test_identical_snapshot_reimport_does_not_duplicate_audit_or_revisions(tmp_path, temp_db):
    """Re-importing an identical batch snapshot does not append audit records or increment revisions."""
    b = _write_batch(tmp_path, "b_snap.json", {
        "projects": [{"id": "p-snap", "name": "Snap Project"}],
        "tasks": [
            {
                "id": "t-snap",
                "project_id": "p-snap",
                "title": "Snap Task",
                "requirements": [
                    {"id": "req-snap", "text": "Snap Req", "status": "active"}
                ]
            }
        ],
        "rules": [
            {
                "id": "rule-snap",
                "project_id": "p-snap",
                "task_id": "t-snap",
                "title": "Snap Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "requirement_id": "req-snap"
            }
        ]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            task_before = tx.workspaces.get_task('t-snap', 'p-snap')
            rev_before = task_before.revision
            audit_count_before = len(tx.audit.project_audit('p-snap'))
            links_before = tx.c.execute(
                sa.select(sa.func.count()).select_from(requirement_rule_links)
            ).scalar_one()
    finally:
        uow.dispose()

    # Re-import identical batch
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            task_after = tx.workspaces.get_task('t-snap', 'p-snap')
            assert task_after.revision == rev_before
            assert len(tx.audit.project_audit('p-snap')) == audit_count_before
            links_after = tx.c.execute(
                sa.select(sa.func.count()).select_from(requirement_rule_links)
            ).scalar_one()
            assert links_after == links_before
    finally:
        uow.dispose()


def test_collection_shapes_and_types_rejected(tmp_path):
    """Reject invalid collection shapes, numeric/null IDs, missing patterns and paths."""
    # 1. projects is a dict instead of list
    b1 = _write_batch(tmp_path, "b1.json", {"projects": {"id": "p"}})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1])
    assert "'projects' must be a list" in str(exc.value)

    # 2. tasks is a number instead of list
    b2 = _write_batch(tmp_path, "b2.json", {"tasks": 42})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2])
    assert "'tasks' must be a list" in str(exc.value)

    # 3. Numeric ID rejected (not silently coerced)
    b3 = _write_batch(tmp_path, "b3.json", {"projects": [{"id": 12345, "name": "P"}]})
    with pytest.raises(ValueError) as exc:
        load_and_validate([b3])
    assert "missing or non-string 'id'" in str(exc.value)

    # 4. Missing rule patterns rejected (does not invent global **)
    b4 = _write_batch(tmp_path, "b4.json", {
        "projects": [{"id": "p", "name": "P"}],
        "rules": [{"id": "r", "project_id": "p", "title": "R", "points": ["P"]}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b4])
    assert "'patterns' is required and must be a non-empty list" in str(exc.value)

    # 5. Missing finding target_path rejected (does not invent src/**)
    b5 = _write_batch(tmp_path, "b5.json", {
        "projects": [{"id": "p", "name": "P"}],
        "tasks": [{"id": "t", "project_id": "p", "title": "T"}],
        "findings": [{"id": "f", "project_id": "p", "task_id": "t", "text": "F"}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b5])
    assert "'target_path' is required" in str(exc.value)

    # 6. Explicit empty task status fails
    b6 = _write_batch(tmp_path, "b6.json", {
        "projects": [{"id": "p", "name": "P"}],
        "tasks": [{"id": "t", "project_id": "p", "title": "T", "status": ""}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b6])
    assert "invalid or empty status" in str(exc.value)

    # 7. Archived requirement without completion summary fails
    b7 = _write_batch(tmp_path, "b7.json", {
        "projects": [{"id": "p", "name": "P"}],
        "tasks": [{
            "id": "t", "project_id": "p", "title": "T", "status": "archived",
            "requirements": [{"id": "r", "text": "R", "status": "archived"}]
        }]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b7])
    assert "archived and requires a non-empty completion summary" in str(exc.value)


def test_main_regression_fixture_and_jit_execution(tmp_path, temp_db):
    """Fixture from regression suite: omitted Task status defaults to active, and JIT succeeds."""
    b = _write_batch(tmp_path, "main_regression.json", {
        "projects": [{"id": "proj-imp", "name": "Imported"}],
        "tasks": [
            {
                "id": "task-imp",
                "project_id": "proj-imp",
                "title": "Task",
                "requirements": [
                    {"id": "req-imp", "text": "  Requirement text preserved  ", "status": "active"}
                ]
            }
        ],
        "rules": [
            {
                "id": "rule-imp",
                "project_id": "proj-imp",
                "task_id": "task-imp",
                "title": "Rule",
                "points": ["P"],
                "patterns": ["src/**"],
                "priority": "P1",
                "category": "business",
                "status": "active"
            }
        ]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            task = tx.workspaces.get_task('task-imp', 'proj-imp')
            assert task is not None
            assert task.status.value == 'active'
            req = tx.requirements.get_requirement('req-imp', 'task-imp')
            assert req.text == "  Requirement text preserved  "

        product = Product(uow)
        agent = Actor('importer-verifier', 'agent')
        task_sess = task_session_id_for('proj-imp', 'task-imp')
        delivery = product.context.get_context(
            agent,
            task_sess,
            ContextQuery(('src/app.py',)),
            'delivery-jit-test'
        )
        assert any(ref[0] == 'rule-imp' for ref in delivery.rule_refs)
        assert any(ref[0] == 'req-imp' for ref in delivery.requirement_refs)
        assert 'Rule' in delivery.markdown or 'Requirement text preserved' in delivery.markdown
    finally:
        uow.dispose()


def test_empty_and_archived_task_creates_no_invented_requirements(tmp_path, temp_db):
    """Archived and empty tasks must not have active requirements invented."""
    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-arch", "name": "Arch Project"}],
        "tasks": [
            {
                "id": "t-arch",
                "project_id": "p-arch",
                "title": "Archived Task with No Reqs",
                "status": "archived",
                "requirements": []
            }
        ]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            task = tx.workspaces.get_task('t-arch', 'p-arch')
            assert task.status.value == 'archived'
            reqs = tx.requirements.project_requirements('p-arch')
            assert len(reqs) == 0
    finally:
        uow.dispose()


def test_failure_rolls_back_atomically(tmp_path, temp_db):
    """If an unhandled error occurs during ingestion, all changes are rolled back."""
    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-rollback", "name": "Rollback Proj"}],
        "tasks": [{"id": "t-rollback", "project_id": "p-rollback", "title": "T", "status": "active"}]
    })
    validated = load_and_validate([b])
    validated.tasks_map['t-rollback']['title'] = None

    with pytest.raises(Exception):
        ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            assert len(tx.workspaces.list_projects()) == 0
    finally:
        uow.dispose()


def test_generated_session_and_worktree_ids_do_not_collide_across_ambiguous_names(tmp_path, temp_db):
    """Distinct projects and tasks with ambiguous names (a/b vs a-b) never collide session IDs."""
    b = _write_batch(tmp_path, "ambiguous.json", {
        "projects": [
            {"id": "a", "name": "Project A"},
            {"id": "a-b", "name": "Project A-B"}
        ],
        "tasks": [
            {"id": "b", "project_id": "a", "title": "Task B in A"},
            {"id": "b-c", "project_id": "a", "title": "Task B-C in A"},
            {"id": "c", "project_id": "a-b", "title": "Task C in A-B"}
        ],
        "rules": [
            {"id": "r-a-b", "project_id": "a", "task_id": "b", "title": "Rule AB", "points": ["P"], "patterns": ["src/**"]},
            {"id": "r-ab-c", "project_id": "a-b", "task_id": "c", "title": "Rule ABC", "points": ["P"], "patterns": ["src/**"]}
        ]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            all_sessions = tx.c.execute(sa.select(sessions)).mappings().all()
            sess_ids = [s['id'] for s in all_sessions]
            # Every generated session ID is strictly unique
            assert len(sess_ids) == len(set(sess_ids))

            # Verify JIT works on both task sessions
            product = Product(uow)
            agent = Actor('verifier', 'agent')
            s1 = task_session_id_for('a', 'b')
            s2 = task_session_id_for('a-b', 'c')
            d1 = product.context.get_context(agent, s1, ContextQuery(('src/app.py',)), 'req-1')
            d2 = product.context.get_context(agent, s2, ContextQuery(('src/app.py',)), 'req-2')
            assert any(ref[0] == 'r-a-b' for ref in d1.rule_refs)
            assert any(ref[0] == 'r-ab-c' for ref in d2.rule_refs)
    finally:
        uow.dispose()


def test_preflight_rejects_reusing_session_or_worktree_of_different_actor(tmp_path, temp_db):
    """Preflight rejects when an existing worktree or session was created by a different actor."""
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.write() as tx:
            tx.workspaces.create_project('p-actor', 'Project Actor')
            wt_id = worktree_id_for('p-actor', 'batch-importer')
            # Seed worktree with a different actor
            tx.c.execute(worktrees.insert().values(
                id=wt_id, project_id='p-actor', actor_id='alien-actor',
                workspace='unknown', machine_name='not_attested', platform='unknown',
                repo_identity=None, git_branch='unknown'
            ))
    finally:
        uow.dispose()

    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-actor", "name": "Project Actor"}]
    })
    validated = load_and_validate([b])
    with pytest.raises(ValueError) as exc:
        ingest_batches(validated, temp_db, dry_run=False)
    assert "worktree" in str(exc.value)
    assert "conflicting provenance attributes" in str(exc.value)


def test_preflight_rejects_rule_with_differing_requirement_links(tmp_path, temp_db):
    """Preflight rejects existing rule when incoming requirement-link set differs."""
    # Seed DB with project, task, requirement, and rule linked to req-1
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.write() as tx:
            tx.workspaces.create_project('p-link', 'P')
            t = codeneuro.modules.tasks.Task('t-link', 'p-link', 'T', '', codeneuro.modules.tasks.TaskStatus.ACTIVE, 1)
            tx.workspaces.create_task(t)
            r = codeneuro.modules.tasks.Requirement('req-1', 'p-link', 't-link', 'Req 1', codeneuro.modules.tasks.RequirementStatus.ACTIVE, 1, None)
            tx.requirements.create_requirement(r, session_id=None, request_id='imp-1')
            rule = codeneuro.modules.knowledge.Rule('rule-1', 'p-link', 't-link', 'Rule 1', ('P',), ('src/**',), codeneuro.modules.knowledge.Priority.P1, 'business', 1, 'active')
            tx.knowledge.create_rule(rule)
            tx.requirements.link_rule('req-1', 'rule-1')
    finally:
        uow.dispose()

    # Batch attempts to re-import rule-1 with NO requirement link (link set mismatch)
    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-link", "name": "P"}],
        "tasks": [{"id": "t-link", "project_id": "p-link", "title": "T", "requirements": [{"id": "req-1", "text": "Req 1"}]}],
        "rules": [{"id": "rule-1", "project_id": "p-link", "task_id": "t-link", "title": "Rule 1", "points": ["P"], "patterns": ["src/**"]}]
    })
    validated = load_and_validate([b])
    with pytest.raises(ValueError) as exc:
        ingest_batches(validated, temp_db, dry_run=False)
    assert "link set mismatch" in str(exc.value)


def test_preflight_rejects_missing_version_snapshot_repair_required(tmp_path, temp_db):
    """Preflight rejects rules/requirements that lack version snapshots (synthetic D31 corrupt DB)."""
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.write() as tx:
            tx.workspaces.create_project('p-corrupt', 'Corrupt DB Project')
            # Manually insert rule WITHOUT corresponding row in rule_versions
            tx.c.execute(rules.insert().values(
                id='rule-corrupt', project_id='p-corrupt', task_id=None,
                title='Unversioned Rule', points_json='["P"]', patterns_json='["src/**"]',
                priority='P1', category='business', status='active', version=1
            ))
    finally:
        uow.dispose()

    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-corrupt", "name": "Corrupt DB Project"}],
        "rules": [{"id": "rule-corrupt", "project_id": "p-corrupt", "title": "Unversioned Rule", "points": ["P"], "patterns": ["src/**"]}]
    })
    validated = load_and_validate([b])

    # Both dry-run and live import reject with repair-required error
    with pytest.raises(ValueError) as exc_dry:
        ingest_batches(validated, temp_db, dry_run=True)
    assert "repair required" in str(exc_dry.value)
    assert "rule-corrupt" in str(exc_dry.value)

    with pytest.raises(ValueError) as exc_live:
        ingest_batches(validated, temp_db, dry_run=False)
    assert "repair required" in str(exc_live.value)


def test_domain_pattern_and_path_validation(tmp_path):
    """Reject Windows backslashes and invalid wildcard patterns in rules and findings."""
    # 1. Backslash in rule pattern
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "rules": [{"id": "r1", "project_id": "p1", "title": "Bad Pattern", "points": ["P"], "patterns": ["src\\windows\\path.py"]}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1])
    assert "invalid domain pattern" in str(exc.value)

    # 2. Invalid segment in pattern
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "rules": [{"id": "r2", "project_id": "p1", "title": "Bad ** segment", "points": ["P"], "patterns": ["src/**.py"]}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2])
    assert "invalid domain pattern" in str(exc.value)

    # 3. Invalid target_path in finding
    b3 = _write_batch(tmp_path, "b3.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "tasks": [{"id": "t1", "project_id": "p1", "title": "T1"}],
        "findings": [{"id": "f1", "project_id": "p1", "task_id": "t1", "text": "F", "target_path": "/absolute/path/forbidden"}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b3])
    assert "invalid domain path/pattern" in str(exc.value)


def test_state_invariants_paused_from_and_strict_statuses(tmp_path):
    """Enforce paused_from on paused tasks and reject active requirements on archived tasks."""
    # 1. Paused task missing paused_from
    b1 = _write_batch(tmp_path, "b1.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "tasks": [{"id": "t1", "project_id": "p1", "title": "T1", "status": "paused"}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b1])
    assert "paused task requires paused_from" in str(exc.value)

    # 2. Paused task with invalid paused_from ('draft')
    b2 = _write_batch(tmp_path, "b2.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "tasks": [{"id": "t1", "project_id": "p1", "title": "T1", "status": "paused", "paused_from": "draft"}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b2])
    assert "paused task requires paused_from in ('active', 'testing')" in str(exc.value)

    # 3. Non-paused task specifying paused_from
    b3 = _write_batch(tmp_path, "b3.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "tasks": [{"id": "t1", "project_id": "p1", "title": "T1", "status": "active", "paused_from": "active"}]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b3])
    assert "non-paused task cannot specify paused_from" in str(exc.value)

    # 4. Archived task with active requirement
    b4 = _write_batch(tmp_path, "b4.json", {
        "projects": [{"id": "p1", "name": "P1"}],
        "tasks": [{
            "id": "t1", "project_id": "p1", "title": "T1", "status": "archived",
            "requirements": [{"id": "r1", "text": "R", "status": "active"}]
        }]
    })
    with pytest.raises(ValueError) as exc:
        load_and_validate([b4])
    assert "archived/released tasks cannot have active requirements" in str(exc.value)


def test_provenance_defaults_are_honest_and_not_hardcoded(tmp_path, temp_db):
    """Missing workspace/machine/branch defaults must be 'unknown' / 'not_attested'."""
    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-honest", "name": "Honest Project"}],
        "tasks": [{"id": "t1", "project_id": "p-honest", "title": "T1", "status": "active"}]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            wts = tx.workspaces.project_worktrees('p-honest')
            assert len(wts) == 1
            assert wts[0].workspace == 'unknown'
            assert wts[0].machine_name == 'not_attested'
            assert wts[0].git_branch == 'unknown'
            assert 'local_dev' not in wts[0].workspace
            assert 'DevStation' not in wts[0].machine_name
    finally:
        uow.dispose()


def test_complete_snapshots_revisions_and_audit(tmp_path, temp_db):
    """Verify version snapshots, task/project revisions, and audit records."""
    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "p-rev", "name": "Revision Project"}],
        "tasks": [
            {
                "id": "t-rev",
                "project_id": "p-rev",
                "title": "Revision Task",
                "status": "active",
                "requirements": [
                    {"id": "req-rev", "text": "Requirement 1", "status": "active"}
                ]
            }
        ],
        "rules": [
            {
                "id": "r-task",
                "project_id": "p-rev",
                "task_id": "t-rev",
                "title": "Task Rule",
                "points": ["Pt 1"],
                "patterns": ["src/**"]
            },
            {
                "id": "r-proj",
                "project_id": "p-rev",
                "title": "Project Rule",
                "points": ["Pt 2"],
                "patterns": ["**"]
            }
        ],
        "findings": [
            {
                "id": "f-rev",
                "project_id": "p-rev",
                "task_id": "t-rev",
                "text": "Finding 1",
                "target_path": "src/app.py"
            }
        ]
    })
    validated = load_and_validate([b])
    ingest_batches(validated, temp_db, dry_run=False)

    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.read() as tx:
            req_snap = tx.c.execute(
                sa.select(requirement_versions).where(requirement_versions.c.requirement_id == 'req-rev')
            ).mappings().first()
            assert req_snap is not None
            assert req_snap['version'] == 1
            assert req_snap['original_text'] == 'Requirement 1'

            rule_snap = tx.knowledge.rule_snapshot('r-task', 1)
            assert rule_snap is not None
            assert rule_snap['title'] == 'Task Rule'

            proj_rev = tx.workspaces.project_revision('p-rev')
            assert proj_rev >= 1

            task = tx.workspaces.get_task('t-rev', 'p-rev')
            assert task.revision >= 3

            audit_records = tx.audit.project_audit('p-rev')
            actions = {rec['action'] for rec in audit_records}
            assert 'project.created' in actions
            assert 'task.created' in actions
            assert 'requirement.created' in actions
            assert 'rule.created' in actions
            assert 'finding.recorded' in actions
    finally:
        uow.dispose()


def test_target_db_collision_detected_in_dry_run(tmp_path, temp_db):
    """Dry-run detects collision with pre-existing conflicting records in target DB."""
    uow = SqliteUnitOfWork(temp_db)
    try:
        with uow.write() as tx:
            tx.workspaces.create_project('proj-exist', 'Existing Name')
    finally:
        uow.dispose()

    b = _write_batch(tmp_path, "b.json", {
        "projects": [{"id": "proj-exist", "name": "Conflicting Name"}]
    })
    validated = load_and_validate([b])

    with pytest.raises(ValueError) as exc:
        ingest_batches(validated, temp_db, dry_run=True)
    assert "Target DB conflict" in str(exc.value)
    assert "proj-exist" in str(exc.value)
