"""Paths in rules are anchored to a workspace, never basename matches."""
from pathlib import Path, PurePosixPath
import re
from .database import DomainError


def relative_path(value: str, *, pattern=False) -> str:
    value = value.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    if (not value or "\x00" in value or value.startswith("/") or
            re.match(r"^[A-Za-z]:", value) or ".." in value.split("/")):
        raise DomainError("Use a non-empty path relative to the registered workspace; '..' is forbidden.")
    if not pattern and any(c in value for c in "*?[]"):
        raise DomainError("A file path cannot contain glob characters.")
    return str(PurePosixPath(value))


def workspace_file(value: str, root: str | None = None) -> str:
    if Path(value).is_absolute():
        if not root:
            raise DomainError("An absolute path requires a registered workspace.")
        try:
            value = str(Path(value).resolve().relative_to(Path(root).resolve()))
        except ValueError:
            raise DomainError("The file is outside the registered workspace.") from None
    result = relative_path(value)
    if root:
        try:
            (Path(root) / result).resolve().relative_to(Path(root).resolve())
        except ValueError:
            raise DomainError("The file resolves through a symlink outside the workspace.") from None
    return result
