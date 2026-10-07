"""Scope Matcher for evaluating glob patterns against file paths with hierarchy awareness."""

import fnmatch
import re
from pathlib import PurePosixPath
from typing import List, Optional, Tuple

from codeneuro.models import Lifecycle, Rule, RuleStatus


def glob_to_regex(pattern: str) -> re.Pattern:
    """Compile glob patterns with support for '**' recursive directory matching."""
    # Normalize slashes and strip leading ./
    pat = pattern.replace("\\", "/").strip()
    if pat.startswith("./"):
        pat = pat[2:]

    # Escape regex special chars except * and ?
    i, n = 0, len(pat)
    res_parts = []
    while i < n:
        c = pat[i]
        if c == "*":
            if i + 1 < n and pat[i + 1] == "*":
                # '**' matches any characters including slashes
                # Check for '/**/' or '**/' or '/**'
                i += 2
                if i < n and pat[i] == "/":
                    res_parts.append("(?:.*/)?")
                    i += 1
                else:
                    res_parts.append(".*")
            else:
                # single '*' matches anything except slash
                res_parts.append("[^/]*")
                i += 1
        elif c == "?":
            res_parts.append("[^/]")
            i += 1
        else:
            res_parts.append(re.escape(c))
            i += 1

    regex_str = f"^{''.join(res_parts)}$"
    return re.compile(regex_str)


class ScopeMatcher:
    def __init__(self):
        self._regex_cache: dict[str, re.Pattern] = {}

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        if pattern not in self._regex_cache:
            self._regex_cache[pattern] = glob_to_regex(pattern)
        return self._regex_cache[pattern]

    def matches_pattern(self, pattern: str, file_path: str) -> bool:
        """Check if file_path matches pattern."""
        norm_path = file_path.replace("\\", "/").strip()
        if norm_path.startswith("./"):
            norm_path = norm_path[2:]

        # Check pure glob
        reg = self._compile_pattern(pattern)
        if reg.match(norm_path):
            return True

        return False

    def matches_rule(self, rule: Rule, file_path: str) -> bool:
        """Check if any of the rule's scope patterns matches the file path."""
        if rule.status != RuleStatus.ACTIVE:
            return False
        for pattern in rule.scope_patterns:
            if self.matches_pattern(pattern, file_path):
                return True
        return False

    def filter_rules(
        self,
        rules: List[Rule],
        file_path: str,
        active_task_id: Optional[str] = None,
    ) -> Tuple[List[Rule], List[Rule]]:
        """
        Filter and split matching rules for a file path into:
        (long_term_rules, short_term_rules)
        Only includes:
          - Active long-term rules matching the path
          - Active short-term rules matching the path AND belonging to active_task_id
        """
        long_term: List[Rule] = []
        short_term: List[Rule] = []

        for rule in rules:
            if not self.matches_rule(rule, file_path):
                continue

            if rule.lifecycle == Lifecycle.LONG_TERM:
                long_term.append(rule)
            elif rule.lifecycle == Lifecycle.SHORT_TERM:
                if active_task_id and rule.task_id == active_task_id:
                    short_term.append(rule)

        # Sort each group by Priority (P0 first, then P1, then P2)
        long_term.sort(key=lambda r: (r.priority.rank, r.created_at))
        short_term.sort(key=lambda r: (r.priority.rank, r.created_at))

        return long_term, short_term
