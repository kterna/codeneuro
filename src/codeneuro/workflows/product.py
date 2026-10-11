"""Explicit composition root for the staged modular-monolith application."""
from ..ports import UnitOfWork
from .workspaces import Workspaces
from .requirements import Requirements
from .knowledge import Knowledge
from .context import Context
from .feedback import Feedback
from .ledger import Ledger
from .governance import Governance


class Product:
    def __init__(self, uow: UnitOfWork):
        self.workspaces = Workspaces(uow)
        self.requirements = Requirements(uow)
        self.knowledge = Knowledge(uow)
        self.context = Context(uow)
        self.feedback = Feedback(uow)
        self.ledger = Ledger(uow)
        self.governance = Governance(uow)
