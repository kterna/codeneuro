"""Inspect current source tokens and shipped assets, without baseline hardcoded colors."""
from pathlib import Path
import hashlib
import json
import re
import sys

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parents[3]
run = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent
files = sorted([*(root/'web/src').rglob('*.vue'), *(root/'web/src').rglob('*.css')])
texts = {p.relative_to(root).as_posix(): p.read_text(encoding='utf-8') for p in files}
definitions = set()
uses = {}
for name, source in texts.items():
    definitions.update(re.findall(r'(--[\w-]+)\s*:', source))
    for match in re.finditer(r'var\(\s*(--[\w-]+)', source):
        uses.setdefault(match[1], []).append({'file':name,'line':source[:match.start()].count('\n')+1})
missing = {name:locations for name,locations in uses.items() if name not in definitions}
shared = ['section-head','toolbar','grid','panel','card','muted','skip-link']
missing_shared = [cls for cls in shared if not any(re.search(r'\.'+re.escape(cls)+r'\s*[{,:>.#\[]', source) for source in texts.values())]
index = (root/'src/codeneuro/static/index.html').read_text(encoding='utf-8')
assets = re.findall(r'(?:src|href)="(/app/assets/[^\"]+)"', index)
asset_info = []
for asset in assets:
    file = root/'src/codeneuro/static'/asset.removeprefix('/app/')
    asset_info.append({'path':file.relative_to(root).as_posix(), 'exists':file.is_file(), 'sha256':hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None})
result = {'source_files':len(files), 'undefined_css_variables':missing,
          'missing_shared_classes':missing_shared, 'shipped_assets':asset_info,
          'contrast_source':'browser-more-results.json:muted_text_contrast_on_current_surfaces (computed current stylesheet colors)'}
(run/'static-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
assert not missing, 'Undefined CSS tokens'
assert not missing_shared, 'Missing shared styles'
assert assets and all(a['exists'] for a in asset_info), 'Missing shipped assets'
