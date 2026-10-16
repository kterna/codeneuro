"""Explicit resource fields shared by create/update MCP operations."""
from typing import Literal
from pydantic import BaseModel, ConfigDict

Action = Literal['create', 'list', 'get', 'update', 'delete']


class TaskChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str | None = None
    description: str | None = None
    status: Literal['draft', 'active', 'testing', 'paused', 'released', 'archived'] | None = None


class RequirementChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str | None = None
    status: Literal['active', 'archived'] | None = None
    summary: str | None = None
