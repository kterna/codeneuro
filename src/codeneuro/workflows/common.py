"""Identifiers and deterministic fingerprints shared by cross-module workflows."""
from dataclasses import asdict
import hashlib
import json
from uuid import uuid4

def _id(prefix):
    return prefix + '_' + uuid4().hex


def _fingerprint(query):
    return hashlib.sha256(json.dumps(asdict(query), sort_keys=True, default=str).encode()).hexdigest()
