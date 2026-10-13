"""Consistent SQLite backup, including committed WAL contents."""
import argparse
from pathlib import Path
import sqlite3
import os

parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path);parser.add_argument('destination',type=Path)
args=parser.parse_args()
if args.destination.exists():parser.error('Destination already exists; choose a new backup name.')
args.destination.parent.mkdir(parents=True,exist_ok=True)
fd = os.open(args.destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
os.close(fd)
try:
    with sqlite3.connect(args.source.resolve().as_uri()+'?mode=ro',uri=True) as source:
        with sqlite3.connect(str(args.destination)) as destination:
            source.backup(destination)
            assert destination.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
except BaseException:
    args.destination.unlink(missing_ok=True)
    raise
print(args.destination.resolve())
