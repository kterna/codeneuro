"""Deterministic JIT selection and rendering; no SQL, I/O or model calls."""
from dataclasses import asdict, dataclass, field
import json

from .findings import Finding
from .knowledge import RANK, Priority, Rule, matches, relative_path
from .topics import validate_keys
from .tasks import ProductError, Requirement


@dataclass(frozen=True)
class ContextQuery:
    priorities: tuple[Priority, ...]
    files: tuple[str, ...] = ()
    topics: tuple[str, ...] = ()
    intent: str = 'implementing'
    mode: str = 'detailed'
    max_chars: int = 24000

    def __post_init__(self):
        if len(self.files) > 50 or len(set(self.files)) != len(self.files):
            raise ProductError('Supply at most 50 distinct files.')
        if not self.files and not self.topics:
            raise ProductError('Supply real files or registered topics, not an empty project-wide query.')
        validate_keys(self.topics)
        if (not self.priorities or any(not isinstance(p, Priority) for p in self.priorities)
                or len(set(self.priorities)) != len(self.priorities)):
            raise ProductError('Explicit distinct priorities are required; there is no default or threshold.')
        object.__setattr__(self, 'priorities', tuple(sorted(self.priorities, key=RANK.__getitem__)))
        object.__setattr__(self, 'topics', tuple(sorted(self.topics)))
        object.__setattr__(self, 'files', tuple(sorted(self.files)))
        for file in self.files:
            relative_path(file)
        if self.intent not in ('implementing', 'debugging') or self.mode not in ('detailed', 'checklist'):
            raise ProductError('Unsupported intent or output mode.')
        if not 512 <= self.max_chars <= 200000:
            raise ProductError('max_chars must be 512–200000.')


@dataclass(frozen=True)
class Delivery:
    id: str
    markdown: str
    rule_refs: tuple[tuple[str, int, str], ...]
    requirement_refs: tuple[tuple[str, int], ...]
    omitted_rule_ids: tuple[str, ...]
    omitted_requirement_ids: tuple[str, ...]
    budget_exceeded: bool
    conflict_assessment: str = 'not_assessed'
    finding_refs: tuple[tuple[str, int], ...] = ()
    omitted_finding_ids: tuple[str, ...] = ()
    sections: dict[str, tuple[dict, ...]] = field(default_factory=dict)
    reported_conflicts: tuple[dict, ...] = ()
    omitted_conflict_ids: tuple[str, ...] = ()
    protocol_version: int = 2
    query: dict = field(default_factory=dict)
    taxonomy_revision: int | None = None
    resolved_topics: tuple[dict, ...] = ()
    match_reasons: dict[str, tuple[str, ...]] = field(default_factory=dict)


def assemble(delivery_id: str, query: ContextQuery, rules: tuple[Rule, ...],
             requirements: tuple[Requirement, ...], known: frozenset[tuple[str, int]],
             findings: tuple[Finding, ...] = (), conflict_reports: tuple[dict, ...] = ()) -> Delivery:
    candidates = [rule for rule in rules if rule.status == 'active' and rule.priority in query.priorities
                  and (rule.is_global or (bool(set(rule.topics) & set(query.topics)) if query.topics
                                          else rule.matches(query.files)))]
    header = (f'CodeNeuro delivery {delivery_id}\nFiles: {", ".join(query.files)}\n'
              f'Topics: {", ".join(query.topics)}\nPriorities: {", ".join(query.priorities)}\n')
    reasons = {}
    entries: list[tuple[str, str, int, str, str, int, int, bool]] = []
    for rule in candidates:
        reminder = rule.priority != Priority.P0 and (rule.id, rule.version) in known
        if reminder:
            content = f'[{rule.priority}] {rule.id}@{rule.version}: already known; recheck if relevant.\n'
        else:
            bullet = '- [ ] ' if query.mode == 'checklist' else '- '
            clauses = '\n'.join(f'{bullet}{p}' for p in rule.points)
            content = f'[{rule.priority}] {rule.title} ({rule.id}@{rule.version})\n{clauses}\n'
        topic_hit = bool(set(rule.topics) & set(query.topics))
        path_hit = rule.matches(query.files)
        reasons[rule.id] = tuple(name for name, hit in (
            ('topic', topic_hit), ('path', path_hit), ('global', rule.is_global)) if hit)
        boost = -(4 * topic_hit + 2 * path_hit)
        entries.append(('rule', rule.id, rule.version, 'reminder' if reminder else 'full',
                        content, RANK[rule.priority], boost, rule.priority == Priority.P0))
    for requirement in requirements:
        if requirement.status != 'active':
            continue
        prefix = '- [ ] ' if query.mode == 'checklist' else '> '
        quote = '\n'.join(f'{prefix}{line}' for line in requirement.text.splitlines())
        content = f'Requirement {requirement.id}@{requirement.version}\n{quote}\n'
        entries.append(('requirement', requirement.id, requirement.version, '', content, 1, -8, False))
    for finding in findings:
        if finding.status != 'pending_review' or finding.priority not in query.priorities:
            continue
        topic_hit = bool(set(finding.topics) & set(query.topics))
        path_hit = bool(finding.target_path) and any(matches(finding.target_path, file) for file in query.files)
        if (topic_hit if query.topics else path_hit):
            bullet = '- [ ] ' if query.mode == 'checklist' else '- '
            text = f'[{finding.priority}] Unreviewed Finding {finding.id}@{finding.version}\n{bullet}{finding.text}\n'
            entries.append(('finding', finding.id, finding.version, '', text, RANK[finding.priority],
                            -(4 * topic_hit + 2 * path_hit + (query.intent == 'debugging')), False))
    current = {(rule.id, rule.version) for rule in candidates}
    for report in conflict_reports:
        refs = tuple(tuple(ref) for ref in report['rule_refs'])
        if len(refs) < 2 or not all(ref in current for ref in refs):
            continue
        content = (f"[Unverified Agent report] Possible conflict {report['id']}: "
                   f"{json.dumps(report['title'], ensure_ascii=False)} (Rule versions: "
                   + ', '.join(f'{rid}@{version}' for rid, version in refs) + ')\n')
        entries.append(('conflict', report['id'], 0, '', content, len(RANK), 0, False))
    entries.sort(key=lambda entry: (entry[5], entry[6], entry[1]))
    selected, omitted = [], []
    length = len(header)
    for entry in entries:
        if entry[7] or length + len(entry[4]) <= query.max_chars:
            selected.append(entry)
            length += len(entry[4])
        else:
            omitted.append(entry)

    def omissions() -> str:
        return ''.join(f'Omitted {kind}s: {", ".join(e[1] for e in omitted if e[0] == kind)}\n'
                       for kind in ('rule', 'requirement', 'finding', 'conflict') if any(e[0] == kind for e in omitted))

    while length + len(omissions()) > query.max_chars:
        last = next((i for i in range(len(selected) - 1, -1, -1) if not selected[i][7]), None)
        if last is None:
            break  # Never cut P0 content; explicitly report the oversize.
        removed = selected.pop(last)
        omitted.append(removed)
        length -= len(removed[4])
    markdown = header + ''.join(e[4] for e in selected) + omissions()
    sections = {'must_obey_contracts': [], 'task_actionable_checklist': [],
                'module_gotchas': [], 'reported_conflicts': []}
    for entry in selected:
        kind, identity, version, representation, content, _, _, mandatory = entry
        bucket = ('must_obey_contracts' if mandatory else 'module_gotchas' if kind == 'finding'
                  else 'reported_conflicts' if kind == 'conflict' else 'task_actionable_checklist')
        sections[bucket].append({'id': identity, 'version': version, 'kind': kind,
                                 'representation': representation or 'full', 'content': content})
    return Delivery(delivery_id, markdown,
        tuple((e[1], e[2], e[3]) for e in selected if e[0] == 'rule'),
        tuple((e[1], e[2]) for e in selected if e[0] == 'requirement'),
        tuple(e[1] for e in omitted if e[0] == 'rule'),
        tuple(e[1] for e in omitted if e[0] == 'requirement'),
        len(markdown) > query.max_chars,
        finding_refs=tuple((e[1], e[2]) for e in selected if e[0] == 'finding'),
        omitted_finding_ids=tuple(e[1] for e in omitted if e[0] == 'finding'),
        sections={name: tuple(items) for name, items in sections.items()},
        reported_conflicts=tuple(report for report in conflict_reports if report['id'] in
                                 {e[1] for e in selected if e[0] == 'conflict'}),
        omitted_conflict_ids=tuple(e[1] for e in omitted if e[0] == 'conflict'),
        query=asdict(query), match_reasons={e[1]: reasons[e[1]] for e in selected if e[0] == 'rule'})
