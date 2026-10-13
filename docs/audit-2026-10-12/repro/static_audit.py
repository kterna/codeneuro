from pathlib import Path
import re,json,sys,hashlib
source,run=map(Path,sys.argv[1:3])
files=list((source/'web/src').rglob('*.vue'))+list((source/'web/src').rglob('*.css'))
texts={str(p.relative_to(source)).replace("\\","/"):p.read_text(encoding='utf-8') for p in files}
declared=set()
uses={}
for name,text in texts.items():
    declared.update(re.findall(r'(--[\w-]+)\s*:',text))
    for m in re.finditer(r'var\((--[\w-]+)',text):
        uses.setdefault(m[1],[]).append({'file':name,'line':text[:m.start()].count('\n')+1})
missing={name:locations for name,locations in uses.items() if name not in declared}
def lum(rgb):
    v=[x/255 for x in rgb]
    v=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in v]
    return sum(a*b for a,b in zip(v,[.2126,.7152,.0722]))
def contrast(a,b):
    x,y=sorted([lum(a),lum(b)])
    return (y+.05)/(x+.05)
out={'undefined_css_variables':missing,'undefined_variable_count':len(missing),
     'undefined_reference_count':sum(map(len,missing.values())),
     'contrast':{'caption_on_sidebar':round(contrast((101,109,118),(22,27,34)),3),
                 'caption_on_canvas':round(contrast((101,109,118),(13,17,23)),3)},
     'media_query_count':sum(len(re.findall(r'@media\b',t)) for t in texts.values()),
     'rules_type_loose_string':"| string" in (source/'web/src/types/ledger.ts').read_text(),
     'missing_shared_classes':[cls for cls in ['section-head','toolbar','grid','panel','card','muted','skip-link']
        if not any(re.search(r'\.'+re.escape(cls)+r'\s*[{,:>]',t) for t in texts.values())],
     'build_byte_match':{}}
for asset in (run/'verified-build/assets').glob('*'):
    original=source/'src/codeneuro/static/assets'/asset.name
    out['build_byte_match'][asset.name]=original.exists() and hashlib.sha256(asset.read_bytes()).digest()==hashlib.sha256(original.read_bytes()).digest()
(run/'static-results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in out.items() if k!='undefined_css_variables'},ensure_ascii=False,indent=2))
print('Undefined tokens:',', '.join(missing))

