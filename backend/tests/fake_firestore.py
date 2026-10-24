"""A small in-memory stand-in for Firestore, just enough for the router transactions.

It mirrors the behaviours that matter for correctness: writes are buffered and applied
only when the transaction function returns, and reading after a write in the same
transaction raises, exactly as Firestore does.
"""
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from google.api_core.exceptions import AlreadyExists, NotFound
from google.cloud import firestore


class ReadAfterWriteError(RuntimeError):
    pass


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0]


class FakeSnapshot:
    def __init__(self, ref: "FakeDocument", data: dict[str, Any] | None):
        self.reference, self.id = ref, ref.id
        self._data = copy.deepcopy(data)
        self.exists = data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._data)

    def get(self, field: str) -> Any:
        return self._data[field]  # KeyError for a missing field, as in Firestore


class FakeDocument:
    def __init__(self, db: "FakeDb", path: str):
        self._db, self.path, self.id = db, path, path.rsplit("/", 1)[-1]

    def get(self, transaction: "FakeTransaction | None" = None) -> FakeSnapshot:
        self._db.check_read(transaction)
        return FakeSnapshot(self, self._db.store.get(self.path))

    def collection(self, name: str) -> "FakeCollection":
        return FakeCollection(self._db, f"{self.path}/{name}")


class FakeQuery:
    def __init__(self, db: "FakeDb", path: str, filters=(), order=None, limit=None):
        self._db, self._path = db, path
        self._filters, self._order, self._limit = filters, order, limit

    def _clone(self, **changes: Any) -> "FakeQuery":
        state = {"filters": self._filters, "order": self._order, "limit": self._limit, **changes}
        return FakeQuery(self._db, self._path, **state)

    def where(self, field: str, op: str, value: Any) -> "FakeQuery":
        assert op in {"==", "in"}, f"fake does not support {op}"
        return self._clone(filters=self._filters + ((field, op, value),))

    def order_by(self, field: str, direction: str = "ASCENDING") -> "FakeQuery":
        return self._clone(order=(field, direction == "DESCENDING"))

    def limit(self, count: int) -> "FakeQuery":
        return self._clone(limit=count)

    def stream(self, transaction: "FakeTransaction | None" = None) -> list[FakeSnapshot]:
        self._db.check_read(transaction)
        rows = [(path, data) for path, data in self._db.store.items() if _parent(path) == self._path]
        for field, op, value in self._filters:
            rows = [(p, d) for p, d in rows if field in d and (d[field] == value if op == "==" else d[field] in value)]
        if self._order:
            field, descending = self._order
            rows = sorted([(p, d) for p, d in rows if field in d], key=lambda row: row[1][field], reverse=descending)
        if self._limit is not None:
            rows = rows[: self._limit]
        return [FakeSnapshot(FakeDocument(self._db, path), data) for path, data in rows]


class FakeCollection(FakeQuery):
    def __init__(self, db: "FakeDb", path: str):
        super().__init__(db, path)

    def document(self, doc_id: str | None = None) -> FakeDocument:
        return FakeDocument(self._db, f"{self._path}/{doc_id or self._db.new_id()}")


class FakeTransaction:
    def __init__(self, db: "FakeDb"):
        self._db, self.writes = db, []

    def get(self, ref: FakeDocument):
        self._db.check_read(self)
        return iter([FakeSnapshot(ref, self._db.store.get(ref.path))])

    def create(self, ref: FakeDocument, data: dict[str, Any]) -> None:
        self.writes.append(("create", ref.path, data))

    def set(self, ref: FakeDocument, data: dict[str, Any]) -> None:
        self.writes.append(("set", ref.path, data))

    def update(self, ref: FakeDocument, data: dict[str, Any]) -> None:
        self.writes.append(("update", ref.path, data))

    def commit(self) -> None:
        store = self._db.store
        staged = dict(store)
        now = self._db.tick()
        for kind, path, data in self.writes:
            resolved = {key: now if value is firestore.SERVER_TIMESTAMP else value for key, value in data.items()}
            if kind == "create" and path in staged:
                raise AlreadyExists(path)
            if kind == "update" and path not in staged:
                raise NotFound(path)
            staged[path] = {**staged.get(path, {}), **resolved} if kind == "update" else copy.deepcopy(resolved)
        store.clear()
        store.update(staged)
        self.writes = []


class FakeDb:
    def __init__(self) -> None:
        self.store: dict[str, dict[str, Any]] = {}
        self._clock = datetime(2028, 1, 1, tzinfo=timezone.utc)
        self._ids = 0

    def tick(self) -> datetime:
        self._clock += timedelta(seconds=1)
        return self._clock

    def new_id(self) -> str:
        self._ids += 1
        return f"auto{self._ids:04d}"

    def check_read(self, transaction: FakeTransaction | None) -> None:
        if transaction is not None and transaction.writes:
            raise ReadAfterWriteError("Firestore transactions must read before they write")

    def collection(self, name: str) -> FakeCollection:
        return FakeCollection(self, name)

    def document(self, path: str) -> FakeDocument:
        return FakeDocument(self, path)

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)


def fake_transactional(function):
    def run(transaction: FakeTransaction, *args: Any, **kwargs: Any):
        transaction.writes = []
        try:
            result = function(transaction, *args, **kwargs)
        except BaseException:
            transaction.writes = []  # nothing is applied when the function fails
            raise
        transaction.commit()
        return result

    return run


class FakeAuth:
    """Firebase Auth stand-in that records what happens to sign-in accounts."""

    class EmailAlreadyExistsError(Exception):
        pass

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.revoked: list[str] = []

    def create_user(self, email: str, password: str, disabled: bool = False) -> SimpleNamespace:
        if any(user["email"] == email for user in self.users.values()):
            raise self.EmailAlreadyExistsError(email)
        uid = f"uid_new_{len(self.users)}"
        self.users[uid] = {"email": email, "password": password, "disabled": disabled}
        return SimpleNamespace(uid=uid)

    def update_user(self, uid: str, **changes: Any) -> None:
        self.users[uid].update(changes)

    def delete_user(self, uid: str) -> None:
        del self.users[uid]

    def revoke_refresh_tokens(self, uid: str) -> None:
        self.revoked.append(uid)
