"""Bounded, non-executing repository indexing and untrusted manifest validation.

Python definitions/imports/calls use AST. JS/TS definitions/imports/HTTP routes use
lexical patterns and are explicitly labelled as approximate. No source is executed.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

from .database import DomainError
from .paths import relative_path

SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', 'dist', 'build',
             '.next', '.mypy_cache', '.pytest_cache', '.codeneuro', 'coverage',
             '.ssh', '.aws', '.azure', '.gnupg', '.codex', '.hermes', '.claude', '.gcloud'}
SOURCE_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte',
                   '.html', '.css', '.md', '.toml'}
LIMITATIONS = ['Static analysis does not execute code or resolve dynamic imports, reflection or generated routes.',
              'JavaScript/TypeScript entities and calls are lexical approximations; aliases and type dispatch may be unresolved.',
              'Endpoint edges match literal paths; runtime base URLs, router mounts and proxy rewrites require review.']


def is_indexable_path(path: str) -> bool:
    """Portable inclusion policy; check before opening a repository file."""
    try:
        canonical = relative_path(path)
    except (DomainError, AttributeError):
        return False
    parts = tuple(p.lower() for p in PurePosixPath(canonical).parts)
    filename = parts[-1]
    if any(p in SKIP_DIRS or p.startswith('.env') for p in parts):
        return False
    if any(parts[i:i + 2] == ('.config', 'gcloud') for i in range(len(parts) - 1)):
        return False
    if filename.split('.')[0] in {'secret', 'secrets', 'credential', 'credentials', 'token', 'tokens', 'id_rsa', 'id_ed25519', 'id_ecdsa', 'id_dsa'}:
        return False
    if filename in {'auth.toml', 'auth.md', 'config.credentials.toml'}:
        return False
    return PurePosixPath(canonical).suffix.lower() in SOURCE_SUFFIXES


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def entity_id(path, kind, name, line):
    return 'ent_' + digest(f'{path}\0{kind}\0{name}\0{line}')[:24]


def _entity(path, kind, name, line, end_line, signature='', summary='', **extra):
    return dict(id=entity_id(path, kind, name, line), path=path, kind=kind, name=name,
                line=line, end_line=end_line, signature=signature[:700], summary=summary[:1000], **extra)


def _literal(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def parse_file(path: str, source: str) -> dict:
    path = relative_path(path)
    lines = source.splitlines()
    result = dict(path=path, sha256=digest(source), line_count=max(1, len(lines)),
                  language='python' if path.lower().endswith('.py') else Path(path).suffix.lower().lstrip('.'),
                  entities=[], references=[], limitations=[])
    entities, refs = result['entities'], result['references']
    entities.append(_entity(path, 'file', path, 1, max(1, len(lines)), summary='\n'.join(lines[:12])[:1000]))
    if path.lower().endswith('.py'):
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            result['limitations'].append(f'Python syntax error at line {exc.lineno}; only file entity indexed.')
            return result

        router_prefixes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for kw in node.value.keywords:
                    prefix = _literal(kw.value)
                    if kw.arg in {'prefix', 'url_prefix'} and prefix is not None:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                router_prefixes[target.id] = prefix

        def visit(node, prefix=''):
            for child in ast.iter_child_nodes(node):
                nested = prefix
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    name = prefix + child.name
                    kind = 'class' if isinstance(child, ast.ClassDef) else 'function'
                    entities.append(_entity(path, kind, name, child.lineno, child.end_lineno,
                                            lines[child.lineno - 1].strip(), ast.get_docstring(child) or ''))
                    nested = name + '.'
                    for dec in child.decorator_list:
                        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.args:
                            route = _literal(dec.args[0])
                            method = dec.func.attr.lower()
                            if route and method in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'route', 'api_route'}:
                                if isinstance(dec.func.value, ast.Name):
                                    route = router_prefixes.get(dec.func.value.id, '').rstrip('/') + route
                                methods = [method.upper()]
                                if method in {'route', 'api_route'}:
                                    methods = ['ANY']
                                    for kw in dec.keywords:
                                        if kw.arg == 'methods' and isinstance(kw.value, (ast.List, ast.Tuple)):
                                            methods = [v.value.upper() for v in kw.value.elts if isinstance(v, ast.Constant) and isinstance(v.value, str)]
                                for verb in methods:
                                    entities.append(_entity(path, 'endpoint', f'{verb} {route}', dec.lineno, child.end_lineno,
                                                            lines[dec.lineno - 1].strip(), method=verb, route=route))
                if isinstance(child, ast.Import):
                    for item in child.names:
                        refs.append(dict(kind='import', target=item.name, line=child.lineno, alias=item.asname or item.name))
                elif isinstance(child, ast.ImportFrom):
                    refs.append(dict(kind='import', target='.' * child.level + (child.module or ''), line=child.lineno,
                                     symbols=[v.name for v in child.names], bindings={v.asname or v.name: v.name for v in child.names}))
                elif isinstance(child, ast.Call):
                    try:
                        target = ast.unparse(child.func)
                    except (ValueError, RecursionError):
                        target = ''
                    if target:
                        refs.append(dict(kind='call', target=target[:500], line=child.lineno))
                visit(child, nested)
        visit(tree)
    elif Path(path).suffix.lower() in {'.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs', '.vue', '.svelte'}:
        # Strip comments without changing line offsets; pattern analysis remains explicitly approximate.
        clean = re.sub(r'/\*[\s\S]*?\*/|(?m:^\s*//.*$)', lambda m: '\n' * m.group().count('\n'), source)
        patterns = [
            ('class', r'\b(?:export\s+)?class\s+([A-Za-z_$][\w$]*)'),
            ('interface', r'\b(?:export\s+)?(?:interface|type)\s+([A-Za-z_$][\w$]*)'),
            ('function', r'\b(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\('),
            ('component', r'\b(?:const|let)\s+([A-Z][\w$]*)\s*=\s*(?:async\s*)?(?:\([^;]*?\)|[\w$]+)\s*=>'),
            ('function', r'\b(?:const|let)\s+([a-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^;]*?\)|[\w$]+)\s*=>'),
        ]
        for kind, pattern in patterns:
            for match in re.finditer(pattern, clean):
                line = clean.count('\n', 0, match.start()) + 1
                entities.append(_entity(path, kind, match[1], line, line, lines[line - 1].strip(), approximation=True))
        for match in re.finditer(r'''(?:\bfrom\s*|\bimport\s*|\brequire\s*\()\s*['"]([^'"]+)['"]''', clean):
            refs.append(dict(kind='import', target=match[1], line=clean.count('\n', 0, match.start()) + 1))
        for match in re.finditer(r'''\b(?:app|router|server)\.(get|post|put|patch|delete|all)\s*\(\s*['"]([^'"]+)['"]''', clean):
            line = clean.count('\n', 0, match.start()) + 1
            method = 'ANY' if match[1] == 'all' else match[1].upper()
            entities.append(_entity(path, 'endpoint', f'{method} {match[2]}', line, line,
                                    lines[line - 1].strip(), method=method, route=match[2], approximation=True))
        for match in re.finditer(r'''\b(fetch|axios\.(?:get|post|put|patch|delete))\s*\(\s*['"`]([^'"`]+)['"`]''', clean):
            explicit = re.search(r'''\bmethod\s*:\s*['"](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['"]''', clean[match.end():match.end() + 300], re.I)
            refs.append(dict(kind='http_call', target=match[2], line=clean.count('\n', 0, match.start()) + 1,
                             method=match[1].split('.')[-1].upper() if '.' in match[1] else explicit[1].upper() if explicit else 'ANY'))
    return result


def build_manifest(root: str | Path, *, max_files=5000, max_file_bytes=500_000, max_total_bytes=20_000_000) -> dict:
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise DomainError('Index root must be an existing directory.')
    files, warnings, total = [], [], 0
    try:
        try:
            listing = subprocess.run(['git', '-C', str(root), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                                     capture_output=True, timeout=15, check=False)
        except OSError:
            listing = None
            warnings.append('Git is unavailable; directory scan cannot apply Git ignore rules.')
        if listing and listing.returncode == 0:
            paths = sorted(set(listing.stdout.decode('utf-8').split('\0')) - {''})
        else:
            paths = []
            for current, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith('.'))
                paths.extend(str((Path(current) / n).relative_to(root)) for n in sorted(names))
    except (subprocess.SubprocessError, UnicodeError):
        raise DomainError('Could not enumerate repository safely.') from None
    for path in paths:
        if not is_indexable_path(path):
            continue
        parts = Path(path).parts
        file = root / path
        if any(root.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)) or not file.is_file():
            continue
        if not file.resolve().is_relative_to(root):
            continue
        size = file.stat().st_size
        if len(files) >= max_files or total + size > max_total_bytes:
            warnings.append('Repository index truncated by configured file/byte limits.')
            break
        if size > max_file_bytes:
            warnings.append(f'{path}: skipped oversized file.')
            continue
        try:
            source = file.read_text(encoding='utf-8')
            if '\x00' in source:
                continue
            if re.search(r'-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----', source):
                warnings.append(f'{path}: excluded private-key material.')
                continue
            files.append(parse_file(path, source))
            total += size
        except (UnicodeError, OSError):
            warnings.append(f'{path}: unreadable or non-UTF-8 file.')
    try:
        commit = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        commit = None
    return dict(schema_version=1, files=files, git_commit=commit.stdout.strip() if commit and commit.returncode == 0 else None,
                limitations=LIMITATIONS + warnings)


def validate_manifest(manifest: dict) -> dict:
    """Treat clients as untrusted: canonical paths, bounded content, consistent IDs/locations."""
    if not isinstance(manifest, dict) or manifest.get('schema_version') != 1:
        raise DomainError('Unsupported index manifest schema.')
    if len(json.dumps(manifest, ensure_ascii=False)) > 40_000_000:
        raise DomainError('Manifest exceeds 40 MB limit.')
    files = manifest.get('files')
    if not isinstance(files, list) or len(files) > 5000:
        raise DomainError('Manifest files must be an array with at most 5000 files.')
    seen, ids, clean = set(), set(), []
    for item in files:
        if not isinstance(item, dict):
            raise DomainError('Invalid manifest file.')
        path = relative_path(str(item.get('path', '')))
        if path in seen or not is_indexable_path(path):
            raise DomainError('Duplicate or excluded manifest path.')
        seen.add(path)
        count = item.get('line_count', 0)
        if type(count) is not int or not 1 <= count <= 1_000_000 or not re.fullmatch(r'[a-f0-9]{64}', str(item.get('sha256', ''))):
            raise DomainError('Manifest file requires SHA256 and valid line_count.')
        entities, refs = item.get('entities', []), item.get('references', [])
        if not isinstance(entities, list) or not isinstance(refs, list) or len(entities) + len(refs) > 10000:
            raise DomainError('Invalid or oversized entity/reference list.')
        checked = []
        for ent in entities:
            if not isinstance(ent, dict) or ent.get('kind') not in {'file', 'class', 'function', 'interface', 'component', 'endpoint'}:
                raise DomainError('Unsupported graph entity kind.')
            line, end = ent.get('line'), ent.get('end_line')
            if type(line) is not int or type(end) is not int or not 1 <= line <= end <= count:
                raise DomainError('Entity evidence outside file bounds.')
            name = str(ent.get('name', ''))
            if not name or len(name) > 1000:
                raise DomainError('Invalid entity name.')
            expected = entity_id(path, ent['kind'], name, line)
            if ent.get('id', expected) != expected or expected in ids or ent.get('path', path) != path:
                raise DomainError('Entity identity does not match its source location.')
            ids.add(expected)
            val = _entity(path, ent['kind'], name, line, end, str(ent.get('signature', '')), str(ent.get('summary', '')))
            if ent['kind'] == 'endpoint':
                val.update(route=str(ent.get('route', ''))[:1000], method=str(ent.get('method', 'ANY')).upper())
            if ent.get('approximation'):
                val['approximation'] = True
            checked.append(val)
        cleaned_refs = []
        for ref in refs:
            if not isinstance(ref, dict) or ref.get('kind') not in {'import', 'call', 'http_call'}:
                raise DomainError('Invalid reference kind.')
            if type(ref.get('line')) is not int or not 1 <= ref['line'] <= count:
                raise DomainError('Reference evidence outside file bounds.')
            target = str(ref.get('target', ''))
            if not target or len(target) > 1000:
                raise DomainError('Invalid reference target.')
            symbols, bindings = ref.get('symbols', []), ref.get('bindings', {})
            if not isinstance(symbols, list) or not isinstance(bindings, dict) or len(bindings) > 100:
                raise DomainError('Invalid import bindings.')
            cleaned_refs.append(dict(kind=ref['kind'], target=target, line=ref['line'], method=str(ref.get('method', 'ANY')),
                                     symbols=[str(s)[:200] for s in symbols[:100]], alias=str(ref.get('alias', ''))[:200],
                                     bindings={str(k)[:200]: str(v)[:200] for k, v in bindings.items()}))
        clean.append(dict(path=path, sha256=item['sha256'], line_count=count, language=str(item.get('language', ''))[:30],
                          entities=checked, references=cleaned_refs,
                          limitations=[str(s)[:500] for s in item.get('limitations', [])[:20]]))
    return dict(schema_version=1, files=clean, git_commit=str(manifest.get('git_commit') or '')[:100],
                limitations=LIMITATIONS + [str(s)[:500] for s in manifest.get('limitations', [])[:100]])


def graph_from_manifest(manifest: dict) -> dict:
    entities = [e for f in manifest['files'] for e in f['entities']]
    files = [{k: v for k, v in f.items() if k not in {'entities', 'references'}} for f in manifest['files']]
    paths = {f['path'] for f in files}
    by_name = {}
    for ent in entities:
        by_name.setdefault(ent['name'], []).append(ent)
    edges = []
    def edge(source, target, kind, path, line, **rest):
        edges.append(dict(source=source, target=target, kind=kind, path=path, line=line, **rest))
    for f in manifest['files']:
        imported_symbols = {}
        imported_modules = {}
        for ent in f['entities']:
            if ent['kind'] != 'file':
                edge(f['path'], ent['id'], 'defines', f['path'], ent['line'])
        for ref in sorted(f['references'], key=lambda r: r['kind'] != 'import'):
            target, resolved = ref['target'], []
            if ref['kind'] == 'import':
                if f['language'] == 'python':
                    level = len(target) - len(target.lstrip('.'))
                    prefix = list(PurePosixPath(f['path']).parent.parts)
                    module = target.lstrip('.').replace('.', '/')
                    base = '/'.join(prefix[:len(prefix) - level + 1] + [module]) if level else module
                    candidates = [base + '.py', base + '/__init__.py', 'src/' + base + '.py', 'src/' + base + '/__init__.py']
                    for symbol in ref.get('symbols', []):
                        candidates += [base.rstrip('/') + '/' + symbol + '.py']
                else:
                    base = str(PurePosixPath(f['path']).parent / target) if target.startswith('.') else target
                    base = os.path.normpath(base).replace('\\', '/')
                    candidates = [base] + [base + s for s in ('.ts', '.tsx', '.js', '.jsx', '/index.ts', '/index.js')]
                resolved = [v for v in candidates if v in paths]
                if resolved:
                    if ref.get('alias'):
                        imported_modules[ref['alias']] = resolved
                    for alias, name in ref.get('bindings', {}).items():
                        imported_symbols[alias] = [e['id'] for e in entities if e['path'] in resolved and e['name'] == name]
            elif ref['kind'] == 'call':
                name = target.split('.')[-1]
                matches = [e for e in entities if e['path'] == f['path'] and e['name'].split('.')[-1] == name and e['kind'] in {'function', 'class'}]
                if len(matches) == 1:
                    resolved = [matches[0]['id']]
                elif target in imported_symbols:
                    resolved = imported_symbols[target]
                elif '.' in target:
                    module, symbol = target.rsplit('.', 1)
                    resolved = [e['id'] for e in entities if e['path'] in imported_modules.get(module, []) and e['name'] == symbol]
            elif ref['kind'] == 'http_call':
                def canonical(route):
                    route = re.sub(r'^https?://[^/]+', '', route).split('?')[0]
                    return re.sub(r'\{[^}]+\}|:[A-Za-z_]\w*|\$\{[^}]+\}', '{}', route)
                resolved = [e['id'] for e in entities if e['kind'] == 'endpoint' and
                            canonical(e.get('route', '')) == canonical(target) and
                            (ref.get('method') == 'ANY' or e.get('method') in {'ANY', ref.get('method')})]
            for destination in resolved or [target]:
                edge(f['path'], destination, ref['kind'], f['path'], ref['line'], resolved=bool(resolved),
                     confidence='static' if f['language'] == 'python' else 'approximate')
    return dict(files=files, entities=entities, edges=edges, git_commit=manifest.get('git_commit'),
                limitations=list(dict.fromkeys(manifest.get('limitations', []))))
