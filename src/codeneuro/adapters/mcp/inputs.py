"""Explicit resource fields shared by MCP and HTTP adapters."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal['create', 'list', 'get', 'update', 'delete']
TaskState = Literal['draft', 'active', 'testing', 'paused', 'completed']
RequirementState = Literal['draft', 'active', 'accepting', 'completed']


class Changes(BaseModel):
    model_config = ConfigDict(extra='forbid')

    @model_validator(mode='after')
    def explicit_values(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError('Omit unchanged fields; explicitly supplied values cannot be null.')
        return self


class TaskChanges(Changes):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = None
    acceptance_criteria: str | None = None
    status: TaskState | None = None
    archived: bool | None = None
    verification_summary: str | None = None
    verification_report_ids: list[str] | None = None


class RequirementChanges(Changes):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    text: str | None = None
    acceptance_criteria: str | None = None
    status: RequirementState | None = None
    completion_summary: str | None = None
    archived: bool | None = None


class Source(Changes):
    workspace: str | None = Field(default=None, max_length=4096)
    machine_name: str | None = Field(default=None, max_length=255)
    platform: str | None = Field(default=None, max_length=16)
    repo_identity: str | None = Field(default=None, max_length=128)
    git_branch: str | None = Field(default=None, max_length=255)
