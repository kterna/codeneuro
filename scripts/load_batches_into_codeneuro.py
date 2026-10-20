#!/usr/bin/env python
"""Import reviewed business records atomically.

Requirements are project parents; Tasks reference requirement_id. New business
records start draft or active. Normative active rules require their review basis;
test-backed rules enter as Task drafts without invented evidence.
"""
import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
import sys
from typing import Literal

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))

from pydantic import BaseModel, ConfigDict, Field
from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
from codeneuro.modules.findings import Finding
from codeneuro.modules.governance import validate_plan
from codeneuro.modules.knowledge import Priority, Rule, relative_path, validate_rule
from codeneuro.modules.tasks import Requirement, RequirementStatus, Task, TaskStatus
from codeneuro.modules.topics import Topic, validate_definition
from codeneuro.workflows.common import _id
from codeneuro.workflows.topics import require_topics

DEFAULT_ACTOR_ID = 'reviewed-batch-importer'


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class ProjectInput(Input):
    id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
    name: str = Field(min_length=1, max_length=500)


class Record(Input):
    id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$')
    project_id: str


class RequirementInput(Record):
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1)
    acceptance_criteria: str = ''
    status: Literal['draft', 'active'] = 'active'


class TaskInput(Record):
    requirement_id: str
    title: str = Field(min_length=1, max_length=500)
    description: str = ''
    acceptance_criteria: str = ''
    status: Literal['draft', 'active'] = 'active'


class RuleInput(Record):
    task_id: str | None = None
    title: str = Field(min_length=1, max_length=500)
    points: list[str] = Field(min_length=1)
    patterns: list[str]
    priority: Literal['P0', 'P1', 'P2', 'P3'] = 'P1'
    topics: list[str]
    status: Literal['draft', 'active'] = 'draft'
    is_global: bool = False
    priority_reason: str = ''
    validation_spec: dict


class FindingInput(Record):
    task_id: str
    text: str = Field(min_length=1)
    target_path: str | None = None
    priority: Literal['P0', 'P1', 'P2', 'P3'] = 'P1'
    topics: list[str] = Field(min_length=1)
    status: Literal['pending_review', 'resolved'] = 'pending_review'


class TopicInput(Input):
    project_id: str
    key: str
    name: str
    description: str


MODELS = {'projects': ProjectInput, 'requirements': RequirementInput, 'tasks': TaskInput,
          'topics': TopicInput, 'rules': RuleInput, 'findings': FindingInput}


@dataclass
class ValidatedBatches:
    records: dict


def load_and_validate(files):
    records = {name: {} for name in MODELS}
    for filename in files:
        data = json.loads(Path(filename).read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - set(MODELS):
            raise ValueError('Expected an object containing projects, requirements, tasks, topics, rules or findings.')
        for name, model in MODELS.items():
            entries = data.get(name, [])
            if not isinstance(entries, list): raise ValueError(f'{name} must be a list.')
            for entry in entries:
                item = model.model_validate(entry).model_dump()
                key = (item['project_id'], item['key']) if name == 'topics' else item['id']
                previous = records[name].get(key)
                if previous is not None and previous != item: raise ValueError(f'Conflicting {name} ID: {key}')
                for field in ('title', 'name', 'text'):
                    if field in item and not item[field].strip(): raise ValueError(f'{name}.{field} cannot be blank.')
                records[name][key] = item
    for name in MODELS.keys() - {'projects'}:
        for item in records[name].values():
            if item['project_id'] not in records['projects']:
                raise ValueError(f"{name}: unknown project_id {item['project_id']}; include its project declaration.")
    for item in records['tasks'].values():
        parent = records['requirements'].get(item['requirement_id'])
        if not parent or parent['project_id'] != item['project_id']:
            raise ValueError('Task requires an explicitly declared parent Requirement in the same project.')
        if parent['status'] == 'draft' and item['status'] != 'draft':
            raise ValueError('A draft Requirement only accepts draft Tasks.')
    for name in ('rules', 'findings'):
        for item in records[name].values():
            if item.get('task_id'):
                task = records['tasks'].get(item['task_id'])
                if not task or task['project_id'] != item['project_id']:
                    raise ValueError(f'{name}: Task must be explicitly declared in the same project.')
                parent = records['requirements'][task['requirement_id']]
                if task['status'] != 'active' or parent['status'] != 'active':
                    raise ValueError('Task knowledge needs an active Task and Requirement.')
            if len(set(item['topics'])) != len(item['topics']): raise ValueError('Duplicate topics.')
            if name == 'rules':
                rule = entity(name, item)
                validate_rule(rule)
                validate_plan(rule.validation_spec, len(rule.points))
                if rule.validation_spec['kind'] == 'test' and (rule.status != 'draft' or not rule.task_id):
                    raise ValueError('Test-backed imports require a Task draft; do not invent successful evidence.')
                if rule.status == 'draft' and not rule.task_id: raise ValueError('A draft Rule requires a Task.')
            elif item['target_path'] is not None:
                relative_path(item['target_path'], pattern=True)
    for item in records['topics'].values():
        validate_definition(item['key'], item['name'], item['description'])
    return ValidatedBatches(records)


def entity(name, item):
    values = dict(item)
    if name == 'requirements':
        return Requirement(**{**values, 'status': RequirementStatus(values['status']), 'original_text': values['text']})
    if name == 'tasks': return Task(**{**values, 'status': TaskStatus(values['status'])})
    if name in ('rules', 'findings'):
        values.update(priority=Priority(values['priority']), topics=tuple(sorted(values['topics'])))
    if name == 'rules': return Rule(**{**values, 'version': 1, 'points': tuple(values['points']), 'patterns': tuple(values['patterns'])})
    if name == 'findings': return Finding(**values)
    if name == 'topics': return Topic(**values)
    return values


def ingest_batches(batches, db_file, dry_run=False):
    if not isinstance(batches, ValidatedBatches): raise ValueError('Validate the complete batch before ingestion.')
    uow = SqliteUnitOfWork(str(db_file))
    try:
        transaction = uow.read if dry_run else uow.write
        with transaction() as tx:
            getters = {
                'projects': lambda item: next((row for row in tx.workspaces.list_projects() if row['id'] == item['id']), None),
                'requirements': lambda item: tx.requirements.get_requirement(item['id']),
                'tasks': lambda item: tx.workspaces.get_task(item['id']),
                'rules': lambda item: tx.knowledge.get_rule(item['id']),
                'findings': lambda item: tx.context.get_finding(item['id']),
                'topics': lambda item: tx.topics.get(item['project_id'], item['key']),
            }
            planned = {name: [] for name in MODELS}
            existing = {name: 0 for name in MODELS}
            for name, records in batches.records.items():
                for item in records.values():
                    current = getters[name](item)
                    if current is None:
                        planned[name].append(entity(name, item))
                    else:
                        snapshot = current if isinstance(current, dict) else asdict(current)
                        if snapshot.get('deleted_at') or snapshot.get('archived_at') or (name == 'topics' and current.status != 'active'):
                            raise ValueError(f'{name}: archived/deleted IDs cannot be reused.')
                        for key, value in item.items():
                            expected, actual = value, snapshot[key]
                            if key == 'topics': expected, actual = sorted(value), sorted(actual)
                            if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
                                raise ValueError(f'{name}: existing record differs at {key}; no overwrite is performed.')
                        if name == 'rules' and not tx.knowledge.rule_snapshot(current.id, current.version):
                            raise ValueError('Existing Rule has no current version snapshot; repair explicitly before import.')
                        if name in ('tasks', 'requirements'):
                            versions = tx.workspaces.task_versions if name == 'tasks' else tx.requirements.versions
                            snapshots = versions(current.id, current.version - 1, 1)
                            if not snapshots or snapshots[0]['version'] != current.version:
                                raise ValueError('Existing resource has no current version snapshot; repair explicitly before import.')
                        existing[name] += 1
            for name in ('rules', 'findings'):
                for item in batches.records[name].values():
                    for key in item['topics']:
                        registered = tx.topics.get(item['project_id'], key)
                        if (item['project_id'], key) not in batches.records['topics'] and (not registered or registered.status != 'active'):
                            raise ValueError(f'Unregistered topic in project {item["project_id"]}: {key}')
            result = {'dry_run': dry_run, 'created': {name: len(items) for name, items in planned.items()}, 'existing': existing}
            if dry_run: return result
            for item in planned['projects']:
                tx.workspaces.create_project(item['id'], item['name'])
                tx.audit.record(item['id'], DEFAULT_ACTOR_ID, 'project.created', item['id'], {'origin': 'reviewed_batch'})
            for name in ('topics', 'requirements', 'tasks', 'rules', 'findings'):
                for item in planned[name]:
                    if name == 'topics': tx.topics.create(item)
                    elif name == 'requirements': tx.requirements.create_requirement(item)
                    elif name == 'tasks':
                        tx.workspaces.create_task(item)
                        parent = tx.requirements.get_requirement(item.requirement_id)
                        tx.requirements.update_requirement(replace(parent, version=parent.version + 1), parent.version)
                    else:
                        require_topics(tx, item.project_id, item.topics)
                        if name == 'findings': tx.context.record_finding(item)
                        else:
                            tx.knowledge.create_rule(item)
                            if item.status == 'draft': tx.governance.create_state(item.id, 1, 30)
                            else:
                                tx.governance.record_review(_id('review'), item.project_id, item.id, 1, True,
                                    item.validation_spec['basis'], DEFAULT_ACTOR_ID)
                    identity = item.key if name == 'topics' else item.id
                    label = {'topics': 'topic', 'requirements': 'requirement', 'tasks': 'task', 'rules': 'rule', 'findings': 'finding'}[name]
                    tx.audit.record(item.project_id, DEFAULT_ACTOR_ID, label + '.imported', identity,
                                    {'origin': 'reviewed_batch', 'historical_reconstruction': False})
            return result
    finally:
        uow.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('files', nargs='+')
    args = parser.parse_args(argv)
    result = ingest_batches(load_and_validate(args.files), args.db, args.dry_run)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
