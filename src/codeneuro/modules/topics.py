"""Project-owned, stable topic definitions; no persistence or transport concerns."""
from dataclasses import dataclass
import re

from .tasks import ProductError


@dataclass(frozen=True)
class Topic:
    project_id: str
    key: str
    name: str
    description: str
    version: int = 1
    status: str = 'active'
    definition_locked: bool = False


def validate_key(key: str):
    if not isinstance(key, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', key) or len(key) > 64:
        raise ProductError('Topic key must be a stable lowercase slug of at most 64 characters.')


def validate_definition(key: str, name: str, description: str):
    validate_key(key)
    if not name.strip() or len(name) > 200 or not description.strip() or len(description) > 2000:
        raise ProductError('A topic needs a bounded name and an explicit business boundary.')


def validate_keys(keys: tuple[str, ...]):
    if len(keys) > 50 or len(set(keys)) != len(keys):
        raise ProductError('Supply at most 50 distinct topic keys.')
    for key in keys:
        validate_key(key)
