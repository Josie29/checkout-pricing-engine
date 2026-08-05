import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from app.promotions import Promotion
from app.seed_loader import SeedLoadError, parse_promotions

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS promotions (
    id TEXT PRIMARY KEY,
    entry TEXT NOT NULL,
    created_at TEXT NOT NULL
)"""


class DuplicatePromotionIdError(ValueError):
    """A promotion was added under an id the store already holds."""


class PromotionStoreLoadError(ValueError):
    """A persisted promotion row could not be restored at startup.

    Raised when a stored row is not valid JSON, no longer passes seed
    validation, disagrees with its own id column, or collides with a seed
    id. Any of these means schema drift or a corrupted database — the store
    fails loud at boot, naming the offending id, rather than silently
    skipping the row and pricing carts against a promotion set the admin
    believes still exists.
    """


class PromotionStore:
    """The seed promotions plus runtime additions persisted to SQLite.

    Seeds stay file-based (`app/seeds/promotions.json`, validated at boot);
    only runtime additions from `POST /promotions` go to the database, as
    one row per promotion holding the raw seed-entry JSON exactly as the
    API accepted it (issue #75). At construction the store replays those
    rows in insertion (rowid) order through the same seed validation the
    API applies, so `all()` returns seeds then additions in insertion
    order — the engine's declaration order — across restarts.

    The database file and its parent directory are created lazily on the
    first write, so constructing the store (and importing `app.main`) has
    no filesystem side effects until a promotion is actually added.

    Connection handling: one short-lived `sqlite3.connect` per operation.
    At admin-API rates the connection setup cost is noise, and it sidesteps
    sqlite3's same-thread rule — uvicorn and TestClient may call from
    different threads, and a shared connection would need
    `check_same_thread=False` plus careful serialization.

    The lock serializes the duplicate-id check with the insert (and guards
    the in-memory list); the `PRIMARY KEY` on `id` is a second line of
    defense should two processes ever share one database file.
    """

    def __init__(self, seeds: Sequence[Promotion], db_path: Path) -> None:
        """Initialize the store with the seeds and any persisted additions.

        Args:
            seeds: The seed promotions, in declaration order. Assumed to
                already have unique ids (the seed loader enforces this).
            db_path: SQLite file holding runtime additions. Loaded if it
                exists; otherwise created (with its parent directory) on
                the first `add()`.

        Raises:
            PromotionStoreLoadError: If any persisted row fails to
                revalidate or collides with a seed id.
        """
        self._lock = threading.Lock()
        self._db_path = db_path
        self._seeds: list[Promotion] = list(seeds)
        self._additions: list[Promotion] = self._load_persisted()

    def all(self) -> list[Promotion]:
        """Every promotion, seeds first, then additions in insertion order.

        Returns:
            A fresh list — callers may not mutate store state through it.
        """
        with self._lock:
            return [*self._seeds, *self._additions]

    def addition_ids(self) -> set[str]:
        """Ids of runtime additions (vs seeds), for API source labeling.

        Returns:
            A fresh set — callers may not mutate store state through it.
        """
        with self._lock:
            return {promotion.id for promotion in self._additions}

    def add(self, promotion: Promotion, entry: Mapping[str, object]) -> None:
        """Add a runtime promotion after the seeds and prior additions.

        Writes through: the entry is persisted before the in-memory list is
        extended, so a promotion the API acknowledged is never lost to a
        restart.

        Args:
            promotion: The validated promotion parsed from `entry`.
            entry: The raw seed-entry mapping exactly as `POST /promotions`
                accepted it; stored verbatim so a restart revalidates the
                same bytes the API did.

        Raises:
            DuplicatePromotionIdError: If a seed or a prior addition already
                uses `promotion.id` (also mapped from the `PRIMARY KEY`
                violation, the on-disk second line of defense).
        """
        with self._lock:
            if any(
                existing.id == promotion.id
                for existing in (*self._seeds, *self._additions)
            ):
                raise DuplicatePromotionIdError(
                    f"promotion id {promotion.id!r} already exists"
                )
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = self._connect()
            try:
                with conn:  # one transaction: schema + insert
                    conn.execute(_SCHEMA)
                    conn.execute(
                        "INSERT INTO promotions (id, entry, created_at)"
                        " VALUES (?, ?, ?)",
                        (
                            promotion.id,
                            json.dumps(dict(entry)),
                            datetime.now(UTC).isoformat(),
                        ),
                    )
            except sqlite3.IntegrityError as exc:
                raise DuplicatePromotionIdError(
                    f"promotion id {promotion.id!r} already exists"
                ) from exc
            finally:
                conn.close()
            self._additions.append(promotion)

    def clear_additions(self) -> None:
        """Drop every runtime addition, keeping the seeds (testing hook).

        Deletes the persisted rows too — otherwise a "restart" in a test
        would resurrect additions a prior test believed cleared. The app
        itself never calls this.
        """
        with self._lock:
            if self._db_path.exists():
                conn = self._connect()
                try:
                    with conn:
                        conn.execute(_SCHEMA)
                        conn.execute("DELETE FROM promotions")
                finally:
                    conn.close()
            self._additions.clear()

    def _connect(self) -> sqlite3.Connection:
        """Open a fresh connection to the store's database file.

        Returns:
            A new connection; callers close it after their one operation
            (see the class docstring for why per-operation connections).
        """
        return sqlite3.connect(self._db_path)

    def _load_persisted(self) -> list[Promotion]:
        """Replay persisted additions through seed validation, in order.

        Returns:
            The stored promotions in insertion (rowid) order; empty when
            the database file does not exist yet.

        Raises:
            PromotionStoreLoadError: If a row is not valid JSON, fails seed
                validation, disagrees with its id column, or duplicates a
                seed id.
        """
        if not self._db_path.exists():
            return []
        conn = self._connect()
        try:
            with conn:
                conn.execute(_SCHEMA)
            rows = cast(
                list[tuple[str, str]],
                conn.execute(
                    "SELECT id, entry FROM promotions ORDER BY rowid"
                ).fetchall(),
            )
        finally:
            conn.close()
        seed_ids = {seed.id for seed in self._seeds}
        additions: list[Promotion] = []
        for row_id, raw_entry in rows:
            try:
                entry = json.loads(raw_entry)
            except json.JSONDecodeError as exc:
                raise PromotionStoreLoadError(
                    f"stored promotion {row_id!r} in {self._db_path}"
                    f" is not valid JSON: {exc}"
                ) from exc
            try:
                promotion = parse_promotions([entry])[0]
            except SeedLoadError as exc:
                raise PromotionStoreLoadError(
                    f"stored promotion {row_id!r} in {self._db_path}"
                    f" no longer validates: {exc}"
                ) from exc
            if promotion.id != row_id:
                raise PromotionStoreLoadError(
                    f"stored promotion {row_id!r} in {self._db_path} has a"
                    f" mismatched entry id {promotion.id!r}"
                )
            if promotion.id in seed_ids:
                raise PromotionStoreLoadError(
                    f"stored promotion {row_id!r} in {self._db_path}"
                    " duplicates a seed promotion id"
                )
            additions.append(promotion)
        return additions
