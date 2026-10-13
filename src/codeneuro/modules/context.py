"""Deterministic JIT selection and rendering; no SQL, I/O or model calls."""
from dataclasses import dataclass, field
import json

from .findings import Finding
from .knowledge import CATEGORIES, RANK, Priority, Rule, matches, relative_path
from .tasks import ProductError, Requirement


@dataclass(frozen=True)
class ContextQuery:
    files: tuple[str, ...]
    min_priority: Priority = Priority.P2
    categories: tuple[str, ...] = ()
    intent: str = 'implementing'
    mode: str = 'detailed'
    max_chars: int = 24000

    def __post_init__(self):
        if not 1 <= len(self.files) <= 50 or len(set(self.files)) != len(self.files):
            raise ProductError('Supply 1–50 distinct files.')
        for file in self.files:
            relative_path(file)
        if not isinstance(self.min_priority, Priority) or set(self.categories) - CATEGORIES:
            raise ProductError('Unsupported priority or category.')
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


def assemble(delivery_id: str, query: ContextQuery, rules: tuple[Rule, ...],
             requirements: tuple[Requirement, ...], known: frozenset[tuple[str, int]],
             findings: tuple[Finding, ...] = (), conflict_reports: tuple[dict, ...] = ()) -> Delivery:
    candidates = [rule for rule in rules if rule.status == 'active' and rule.matches(query.files)
                  and RANK[rule.priority] <= RANK[query.min_priority]
                  and (rule.priority == Priority.P0 or not query.categories or rule.category in query.categories)]
    header = f'CodeNeuro delivery {delivery_id}\nFiles: {", ".join(query.files)}\n'
    entries: list[tuple[str, str, int, str, str, int, int, bool]] = []
    for rule in candidates:
        reminder = rule.priority != Priority.P0 and (rule.id, rule.version) in known
        if reminder:
            content = f'[{rule.priority}] {rule.id}@{rule.version}: already known; recheck if relevant.\n'
        else:
            bullet = '- [ ] ' if query.mode == 'checklist' else '- '
            clauses = '\n'.join(f'{bullet}{p}' for p in rule.points)
            content = f'[{rule.priority}] {rule.title} ({rule.id}@{rule.version})\n{clauses}\n'
        boost = 0 if query.intent == 'debugging' and rule.category == 'gotcha' else 1
        entries.append(('rule', rule.id, rule.version, 'reminder' if reminder else 'full',
                        content, RANK[rule.priority], boost, rule.priority == Priority.P0))
    if RANK[query.min_priority] >= 1 and (not query.categories or 'business' in query.categories):
        for requirement in requirements:
            if requirement.status != 'active':
                continue
            prefix = '- [ ] ' if query.mode == 'checklist' else '> '
            quote = '\n'.join(f'{prefix}{line}' for line in requirement.text.splitlines())
            content = f'[P1] Requirement {requirement.id}@{requirement.version}\n{quote}\n'
            entries.append(('requirement', requirement.id, requirement.version, '', content, 1, -1, False))
    if RANK[query.min_priority] >= 1 and (not query.categories or 'gotcha' in query.categories):
        for finding in findings:
            if finding.status != 'pending_review' or RANK[finding.priority] > RANK[query.min_priority]:
                continue
            if any(matches(finding.target_path, file) for file in query.files):
                bullet = '- [ ] ' if query.mode == 'checklist' else '- '
                text = f'[{finding.priority}] Unreviewed Finding {finding.id}@{finding.version}\n{bullet}{finding.text}\n'
                entries.append(('finding', finding.id, finding.version, '', text,
                                RANK[finding.priority], -2 if query.intent == 'debugging' else 2, False))
    current = {(rule.id, rule.version) for rule in candidates}
    for report in conflict_reports:
        refs = tuple(tuple(ref) for ref in report['rule_refs'])
        if len(refs) < 2 or not all(ref in current for ref in refs):
            continue
        content = (f"[Unverified Agent report] Possible conflict {report['id']}: "
                   f"{json.dumps(report['title'], ensure_ascii=False)} (Rule versions: "
                   + ', '.join(f'{rid}@{version}' for rid, version in refs) + ')\n')
        entries.append(('conflict', report['id'], 0, '', content, 3, 0, False))
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
        omitted_conflict_ids=tuple(e[1] for e in omitted if e[0] == 'conflict'))
