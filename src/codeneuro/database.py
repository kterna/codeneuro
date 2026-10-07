"""SQLite units of work shared by HTTP threads and stdio processes."""
from contextlib import contextmanager
from functools import wraps
import threading


class DomainError(ValueError):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 422):
        super().__init__(message)
        self.code, self.status = code, status


class Conflict(DomainError):
    def __init__(self, message: str):
        super().__init__(message, "conflict", 409)


def atomic(*, write=False):
    def decorate(fn):
        @wraps(fn)
        def call(self, *args, **kwargs):
            with self.transaction(write=write):
                return fn(self, *args, **kwargs)
        return call
    return decorate


class Transactional:
    def _setup_transactions(self):
        self._lock = threading.RLock()
        self._depth = 0

    @contextmanager
    def transaction(self, *, write=True):
        # One connection is shared by FastAPI threads; the lock covers the entire
        # unit of work, including reads used to decide subsequent writes.
        with self._lock:
            depth = self._depth
            marker = f"nested_{depth}"
            self.conn.execute(("BEGIN IMMEDIATE" if write else "BEGIN") if depth == 0
                              else f"SAVEPOINT {marker}")
            self._depth += 1
            try:
                yield self.conn
                self.conn.execute("COMMIT" if depth == 0 else f"RELEASE {marker}")
            except BaseException:
                if depth == 0:
                    self.conn.rollback()
                else:
                    self.conn.execute(f"ROLLBACK TO {marker}")
                    self.conn.execute(f"RELEASE {marker}")
                raise
            finally:
                self._depth -= 1

    def close(self):
        with self._lock:
            self.conn.close()
