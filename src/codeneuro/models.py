"""Core domain models and schema definitions for CodeNeuro."""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class Lifecycle(str, Enum):
    LONG_TERM = "long_term"   # Invariant architectural contracts (Skeleton)
    SHORT_TERM = "short_term" # Ephemeral task/iteration constraints (Bloodstream)


class Priority(str, Enum):
    P0 = "P0" # Critical blocker / architectural redline (must not violate)
    P1 = "P1" # Strict task requirement / test contract
    P2 = "P2" # Pattern / style / best practice recommendation

    @property
    def rank(self) -> int:
        order = {"P0": 0, "P1": 1, "P2": 2}
        return order.get(self.value, 99)


class RuleStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"
    DEPRECATED = "deprecated"


class TaskStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TESTING = "testing"
    RELEASED = "released"
    ARCHIVED = "archived"


class FindingStatus(str, Enum):
    PENDING_REVIEW = "pending_review"
    CRYSTALLIZED = "crystallized" # Promoted to long-term or active rule
    DISCARDED = "discarded"


class IssueType(str, Enum):
    RULE_CONFLICT = "rule_conflict"     # Conflicting rules (e.g. mutually exclusive requirements)
    RULE_OUTDATED = "rule_outdated"     # Rule does not match reality of codebase
    SCOPE_MISSING = "scope_missing"     # Discovered severe gotcha not guarded by any rule
    NOISE_OVERFLOW = "noise_overflow"   # Context window saturated by too many low-value rules
    OTHER = "other"


class IssueStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class Project(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    root_paths: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    description: Optional[str] = ""
    status: TaskStatus = TaskStatus.ACTIVE
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(BaseModel):
    id: str
    project_id: str
    task_id: Optional[str] = None  # None indicates project-wide long-term rule
    scope_patterns: List[str] = Field(default_factory=lambda: ["**"]) # Globs like ["src/services/pay/**"]
    priority: Priority = Priority.P1
    lifecycle: Lifecycle = Lifecycle.SHORT_TERM
    title: str
    content_points: List[str] = Field(default_factory=list)
    created_by: str = "user" # "user" | "agent" | "decomposer"
    status: RuleStatus = RuleStatus.ACTIVE
    hit_count: int = 0
    last_hit_at: Optional[datetime] = None
    avg_score: Optional[float] = None
    eval_count: int = 0
    zero_score_count: int = 0 # Count of 'already known / redundant' evaluations
    one_score_count: int = 0  # Count of 'irrelevant noise' evaluations
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Finding(BaseModel):
    id: str
    project_id: str
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    target_path: str
    finding_text: str
    suggested_priority: Priority = Priority.P1
    status: FindingStatus = FindingStatus.PENDING_REVIEW
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Proposal(BaseModel):
    id: str
    project_id: str
    task_id: Optional[str] = None
    target_component: str
    proposed_contract: str
    justification: str
    status: str = "pending" # pending | approved | rejected
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RuleEvaluation(BaseModel):
    id: str
    project_id: str
    rule_id: str
    score: int = Field(ge=0, le=5) # 0=known/redundant, 1=irrelevant, 2=low quality, 3=neutral, 4=helpful, 5=essential
    file_path: str
    reason: Optional[str] = ""
    session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentIssue(BaseModel):
    id: str
    project_id: str
    issue_type: IssueType = IssueType.OTHER
    title: str
    description: str
    file_path: str
    related_rule_ids: List[str] = Field(default_factory=list)
    suggested_action: Optional[str] = ""
    status: IssueStatus = IssueStatus.OPEN
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class ContextResolution(BaseModel):
    file_path: str
    project_id: str
    task_id: Optional[str] = None
    long_term_rules: List[Rule] = Field(default_factory=list)
    short_term_rules: List[Rule] = Field(default_factory=list)
    matched_findings: List[Finding] = Field(default_factory=list)
    rendered_markdown: str = ""
    debug_mode: bool = False
