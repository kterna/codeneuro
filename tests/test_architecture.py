"""Executable dependency boundaries for the staged modular monolith."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / 'src' / 'codeneuro'


@pytest.mark.parametrize('source', list((ROOT / 'modules').glob('*.py')))
def test_domain_has_no_transport_database_or_legacy_dependencies(source):
    imports = _imports(source)
    forbidden = ('sqlalchemy', 'sqlite3', 'fastapi', 'mcp', 'codeneuro.')
    assert not [name for name in imports if name.startswith(forbidden)], (source, imports)


@pytest.mark.parametrize('source', list((ROOT / 'workflows').glob('*.py')))
def test_workflows_own_transactions_not_sql_or_transport(source):
    imports = _imports(source)
    forbidden = ('sqlalchemy', 'sqlite3', 'fastapi', 'mcp', 'codeneuro.')
    assert not [name for name in imports if name.startswith(forbidden)], (source, imports)


def test_mcp_and_http_do_not_read_database_directly():
    for folder in (ROOT / 'adapters' / 'mcp', ROOT / 'adapters' / 'http'):
        for source in folder.glob('*.py'):
            imports = _imports(source)
            assert not [name for name in imports if name.startswith(('sqlalchemy', 'sqlite3', 'codeneuro.'))]


def _imports(source):
    tree = ast.parse(source.read_text(encoding='utf-8'))
    values = []
    for item in ast.walk(tree):
        if isinstance(item, ast.Import):
            values.extend(entry.name for entry in item.names)
        elif isinstance(item, ast.ImportFrom) and item.level == 0:
            values.append(item.module or '')
    return values
