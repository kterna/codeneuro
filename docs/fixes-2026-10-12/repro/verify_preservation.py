from pathlib import Path
import hashlib
import json
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('D:/1/github/codeneuro')
run = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent
manifest = json.loads((root/'docs/audit-2026-10-12/manifest.json').read_text(encoding='utf-8'))
changed = []
for entry in manifest['files']:
    path = root / entry['path']
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        changed.append(entry['path'])
result = {'audit_manifest_entries':len(manifest['files']), 'changed_evidence':changed,
          'dist_batches_files':sum(p.is_file() for p in (root/'dist_batches').rglob('*'))}
print(json.dumps(result, ensure_ascii=False, indent=2))
(run/'preservation-results.json').write_text(json.dumps(result, indent=2),encoding='utf-8')
assert not changed
assert result['dist_batches_files'] == 270
