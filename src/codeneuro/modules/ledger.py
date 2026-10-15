"""Pure scope-density projection from active rules; does not invent a code tree."""
from collections import defaultdict


def density(rules: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = defaultdict(lambda: {
        'scope': '', 'p0': 0, 'p1': 0, 'p2': 0, 'p3': 0,
        'long_term': 0, 'short_term': 0, 'rule_ids': [],
    })
    for rule in rules:
        if rule['status'] != 'active':
            continue
        scopes = set(rule['patterns'])
        if rule.get('is_global'):
            scopes.add('(global)')
        if not scopes:
            scopes = {'topic:' + key for key in rule['topics']}
        for pattern in scopes:
            segments = pattern.split('/')
            concrete = []
            for part in segments:
                if any(char in part for char in ('*', '?', '[')):
                    break
                concrete.append(part)
            scope = '/'.join(concrete) or '(all files)'
            item = grouped[scope]
            item['scope'] = scope
            item[rule['priority'].lower()] += 1
            item['short_term' if rule['task_id'] else 'long_term'] += 1
            if rule['id'] not in item['rule_ids']:
                item['rule_ids'].append(rule['id'])
    return sorted(grouped.values(), key=lambda item: (-item['p0'],
                  -(item['p1'] + item['p2'] + item['p3']), item['scope']))
