"""Executable dependency boundaries for the staged modular monolith."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'codeneuro'


def _resolve_imports_from_tree(tree: ast.AST, module_path: Path) -> list[str]:
    rel_parts = module_path.relative_to(ROOT.parent).with_suffix('').parts
    # Drop filename for all modules, including __init__.py
    pkg_parts = list(rel_parts[:-1])
    values = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            values.extend(entry.name for entry in item.names)
        elif isinstance(item, ast.ImportFrom):
            if item.level == 0:
                mod = item.module or ''
            else:
                base = pkg_parts[:len(pkg_parts) - (item.level - 1)]
                mod_parts = list(base) + (item.module.split('.') if item.module else [])
                mod = '.'.join(mod_parts)

            if mod:
                values.append(mod)
            for entry in item.names:
                values.append(f"{mod}.{entry.name}" if mod else entry.name)
    return list(dict.fromkeys(values))


def _imports(source: Path) -> list[str]:
    tree = ast.parse(source.read_text(encoding='utf-8'))
    return _resolve_imports_from_tree(tree, source)


def _normalize_violations(violations: list[str]) -> list[str]:
    unique = list(dict.fromkeys(violations))
    result = []
    for item in unique:
        if not any(item != other and item.startswith(other + '.') for other in unique):
            result.append(item)
    return result


def check_domain_imports(imports: list[str]) -> list[str]:
    forbidden = (
        'sqlalchemy', 'sqlite3', 'fastapi', 'mcp', 'starlette',
        'codeneuro.adapters', 'codeneuro.workflows', 'codeneuro.ports',
    )
    raw = [name for name in imports if any(name == f or name.startswith(f + '.') for f in forbidden)]
    return _normalize_violations(raw)


def check_workflow_imports(imports: list[str]) -> list[str]:
    forbidden = (
        'sqlalchemy', 'sqlite3', 'fastapi', 'mcp', 'starlette',
        'codeneuro.adapters',
    )
    raw = [name for name in imports if any(name == f or name.startswith(f + '.') for f in forbidden)]
    return _normalize_violations(raw)


def check_transport_imports(imports: list[str]) -> list[str]:
    forbidden = (
        'sqlalchemy', 'sqlite3', 'codeneuro.adapters.sqlite',
    )
    raw = [name for name in imports if any(name == f or name.startswith(f + '.') for f in forbidden)]
    return _normalize_violations(raw)


@pytest.mark.parametrize('source', list((ROOT / 'modules').glob('*.py')))
def test_domain_has_no_transport_database_or_legacy_dependencies(source):
    imports = _imports(source)
    violations = check_domain_imports(imports)
    assert not violations, f"Domain module {source} has forbidden imports: {violations}"


@pytest.mark.parametrize('source', list((ROOT / 'workflows').glob('*.py')))
def test_workflows_own_transactions_not_sql_or_transport(source):
    imports = _imports(source)
    violations = check_workflow_imports(imports)
    assert not violations, f"Workflow module {source} has forbidden imports: {violations}"


def test_mcp_and_http_do_not_read_database_directly():
    for folder in (ROOT / 'adapters' / 'mcp', ROOT / 'adapters' / 'http'):
        for source in folder.glob('*.py'):
            imports = _imports(source)
            violations = check_transport_imports(imports)
            assert not violations, f"Transport module {source} has forbidden imports: {violations}"


def test_architecture_catches_relative_and_absolute_violations():
    """Negative tests verifying detection of relative and absolute imports violating boundaries."""
    # 1. Domain importing adapter via relative import
    domain_code = "from ..adapters.sqlite import schema\nfrom ..workflows.governance import Governance"
    tree = ast.parse(domain_code)
    domain_path = ROOT / 'modules' / 'fake_domain.py'
    resolved = _resolve_imports_from_tree(tree, domain_path)
    assert 'codeneuro.adapters.sqlite' in resolved
    assert 'codeneuro.workflows.governance' in resolved
    violations = check_domain_imports(resolved)
    assert len(violations) == 2

    # 2. Domain importing adapter via package-level imports: 'from .. import adapters' and 'from codeneuro import adapters'
    alias_rel_code = "from .. import adapters"
    alias_rel_resolved = _resolve_imports_from_tree(ast.parse(alias_rel_code), domain_path)
    assert 'codeneuro.adapters' in alias_rel_resolved
    assert check_domain_imports(alias_rel_resolved) == ['codeneuro.adapters']

    alias_abs_code = "from codeneuro import adapters"
    alias_abs_resolved = _resolve_imports_from_tree(ast.parse(alias_abs_code), domain_path)
    assert 'codeneuro.adapters' in alias_abs_resolved
    assert check_domain_imports(alias_abs_resolved) == ['codeneuro.adapters']

    # 3. Direct absolute import: 'import codeneuro.adapters'
    import_abs_code = "import codeneuro.adapters"
    import_abs_resolved = _resolve_imports_from_tree(ast.parse(import_abs_code), domain_path)
    assert 'codeneuro.adapters' in import_abs_resolved
    assert check_domain_imports(import_abs_resolved) == ['codeneuro.adapters']

    # 4. Workflow importing SQL/adapter via relative import and package-level imports
    workflow_code = "from ..adapters.sqlite.uow import SqliteUnitOfWork\nimport sqlalchemy"
    tree = ast.parse(workflow_code)
    wf_path = ROOT / 'workflows' / 'fake_wf.py'
    resolved = _resolve_imports_from_tree(tree, wf_path)
    assert 'codeneuro.adapters.sqlite.uow' in resolved
    violations = check_workflow_imports(resolved)
    assert len(violations) == 2

    wf_alias_code = "from .. import adapters\nfrom codeneuro import adapters"
    wf_alias_resolved = _resolve_imports_from_tree(ast.parse(wf_alias_code), wf_path)
    assert check_workflow_imports(wf_alias_resolved) == ['codeneuro.adapters']

    # 5. HTTP adapter directly reading sqlite repo via relative import
    adapter_code = "from ..sqlite.audit import AuditRepo"
    tree = ast.parse(adapter_code)
    adapter_path = ROOT / 'adapters' / 'http' / 'fake_api.py'
    resolved = _resolve_imports_from_tree(tree, adapter_path)
    assert 'codeneuro.adapters.sqlite.audit' in resolved
    violations = check_transport_imports(resolved)
    assert len(violations) == 1

    # 6. Transport importing sqlite adapter via relative and absolute alias forms
    transport_rel = "from .. import sqlite"
    t_rel_resolved = _resolve_imports_from_tree(ast.parse(transport_rel), adapter_path)
    assert 'codeneuro.adapters.sqlite' in t_rel_resolved
    assert check_transport_imports(t_rel_resolved) == ['codeneuro.adapters.sqlite']

    transport_abs = "from codeneuro.adapters import sqlite"
    t_abs_resolved = _resolve_imports_from_tree(ast.parse(transport_abs), adapter_path)
    assert 'codeneuro.adapters.sqlite' in t_abs_resolved
    assert check_transport_imports(t_abs_resolved) == ['codeneuro.adapters.sqlite']

    # 7. Correct package handling for __init__.py files
    init_path = ROOT / 'modules' / '__init__.py'
    init_code = "from .. import adapters\nfrom . import tasks"
    init_resolved = _resolve_imports_from_tree(ast.parse(init_code), init_path)
    assert 'codeneuro.adapters' in init_resolved
    assert 'codeneuro.modules.tasks' in init_resolved
    # '__init__' must NOT appear in package segments
    assert not any('__init__' in item for item in init_resolved)
    # adapters is forbidden in domain, tasks is allowed
    assert check_domain_imports(init_resolved) == ['codeneuro.adapters']


def test_architecture_allows_valid_dependencies():
    """Verify that legitimate dependencies within layers are permitted."""
    # Domain can import its own siblings and standard library
    domain_ok = "import json\nfrom .tasks import Task, TaskStatus"
    d_res = _resolve_imports_from_tree(ast.parse(domain_ok), ROOT / 'modules' / 'custom.py')
    assert check_domain_imports(d_res) == []

    # Workflow can import domain modules and ports
    wf_ok = "from ..modules.tasks import Task\nfrom ..ports import UnitOfWork"
    w_res = _resolve_imports_from_tree(ast.parse(wf_ok), ROOT / 'workflows' / 'custom.py')
    assert check_workflow_imports(w_res) == []
