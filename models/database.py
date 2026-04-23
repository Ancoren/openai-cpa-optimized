"""
SQLAlchemy-based database layer with connection pooling.
Replaces the fragile string-replacement dual-engine compatibility in db_manager.py.

Improvements:
- Connection pooling (reduces connection churn)
- Declarative ORM models (type-safe, no SQL string manipulation)
- Automatic SQLite WAL mode / MySQL charset
- Async support ready (can be upgraded to asyncpg/aiomysql later)
- Migration-ready (Alembic compatible)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Generator, Optional

from sqlalchemy import (
    JSON, Column, DateTime, Integer, String, Text, create_engine,
    event, inspect, select
)
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_config

Base = declarative_base()


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(191), unique=True, nullable=False, index=True)
    password = Column(Text)
    token_data = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def status(self) -> str:
        if not self.token_data:
            return "未知"
        if '"access_token"' in self.token_data:
            return "有凭证"
        if '"仅注册成功"' in self.token_data:
            return "仅注册成功"
        return "未知"

    def to_dict(self, include_token: bool = False) -> dict[str, Any]:
        data = {
            "email": self.email,
            "password": self.password,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "status": self.status,
        }
        if include_token and self.token_data:
            try:
                data["token_data"] = json.loads(self.token_data)
            except json.JSONDecodeError:
                data["token_data"] = None
        return data


class LocalMailbox(Base):
    __tablename__ = "local_mailboxes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(191), unique=True, nullable=False, index=True)
    password = Column(Text)
    client_id = Column(Text)
    refresh_token = Column(Text)
    status = Column(Integer, default=0, index=True)
    fission_count = Column(Integer, default=0)
    retry_master = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "password": self.password,
            "client_id": self.client_id,
            "refresh_token": self.refresh_token,
            "status": self.status,
            "fission_count": self.fission_count,
            "retry_master": self.retry_master,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SystemKV(Base):
    __tablename__ = "system_kv"

    key = Column(String(191), primary_key=True)
    value = Column(Text)


class DatabaseManager:
    """Thread-safe database manager with connection pooling."""

    def __init__(self) -> None:
        self._engine = None
        self._session_factory = None

    def init(self) -> None:
        cfg = get_config()
        db_url = cfg.get_db_url()

        if cfg.database.type == "sqlite":
            self._engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                pool_pre_ping=True,
            )
            # Enable WAL mode for better concurrent read/write
            @event.listens_for(self._engine, "connect")
            def _set_sqlite_pragma(dbapi_conn, _):
                dbapi_conn.execute("PRAGMA journal_mode=WAL")
                dbapi_conn.execute("PRAGMA synchronous=NORMAL")
        else:
            self._engine = create_engine(
                db_url,
                pool_size=cfg.database.pool_size,
                max_overflow=cfg.database.max_overflow,
                pool_pre_ping=True,
                pool_recycle=3600,
            )

        self._session_factory = sessionmaker(
            bind=self._engine, expire_on_commit=False
        )
        Base.metadata.create_all(self._engine)

    @contextmanager
    def session(self) -> Generator[Session, None, None]:
        if self._session_factory is None:
            self.init()
        s = self._session_factory()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # --- Account operations ---

    def save_account(self, email: str, password: str, token_data: dict | str) -> bool:
        if isinstance(token_data, dict):
            token_data = json.dumps(token_data, ensure_ascii=False)
        with self.session() as s:
            acc = s.query(Account).filter_by(email=email).first()
            if acc:
                acc.password = password
                acc.token_data = token_data
            else:
                s.add(Account(email=email, password=password, token_data=token_data))
            # Auto-push to Codex Hub if enabled (fire-and-forget, non-blocking)
            try:
                from services.hub_pusher import push_account
                push_account(email, password, token_data)
            except Exception:
                pass  # Never let push failures break registration
            return True

    def get_account_by_email(self, email: str) -> Optional[Account]:
        with self.session() as s:
            return s.query(Account).filter_by(email=email).first()

    def get_accounts_page(
        self, page: int = 1, page_size: int = 50, hide_reg_only: bool = False
    ) -> dict[str, Any]:
        with self.session() as s:
            q = s.query(Account)
            if hide_reg_only:
                q = q.filter(Account.token_data.notlike('%"仅注册成功"%'))
            total = q.count()
            rows = (
                q.order_by(Account.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {"total": total, "data": [r.to_dict() for r in rows]}

    def get_all_accounts_with_token(self, limit: int = 10000) -> list[dict]:
        with self.session() as s:
            rows = (
                s.query(Account)
                .order_by(Account.id.desc())
                .limit(limit)
                .all()
            )
            result = []
            for r in rows:
                item = {"email": r.email, "password": r.password}
                if r.token_data:
                    try:
                        item["token_data"] = json.loads(r.token_data)
                    except json.JSONDecodeError:
                        item["token_data"] = r.token_data
                result.append(item)
            return result

    def delete_accounts(self, emails: list[str]) -> int:
        with self.session() as s:
            return s.query(Account).filter(Account.email.in_(emails)).delete(
                synchronize_session=False
            )

    def account_exists(self, email: str) -> bool:
        with self.session() as s:
            return (
                s.query(Account.id)
                .filter(Account.email == email.strip().lower())
                .first()
                is not None
            )

    def clear_all_accounts(self) -> int:
        with self.session() as s:
            return s.query(Account).delete(synchronize_session=False)

    # --- Mailbox operations ---

    def import_mailboxes(self, mailboxes: list[dict]) -> int:
        count = 0
        with self.session() as s:
            for mb in mailboxes:
                exists = (
                    s.query(LocalMailbox.id)
                    .filter(LocalMailbox.email == mb.get("email"))
                    .first()
                )
                if not exists:
                    s.add(
                        LocalMailbox(
                            email=mb["email"],
                            password=mb.get("password", ""),
                            client_id=mb.get("client_id", ""),
                            refresh_token=mb.get("refresh_token", ""),
                        )
                    )
                    count += 1
        return count

    def get_mailboxes_page(self, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        with self.session() as s:
            total = s.query(LocalMailbox).count()
            rows = (
                s.query(LocalMailbox)
                .order_by(LocalMailbox.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {"total": total, "data": [r.to_dict() for r in rows]}

    def get_and_lock_unused_mailbox(self) -> Optional[dict]:
        with self.session() as s:
            # Subquery for used emails
            used = s.query(Account.email).filter(
                Account.email == LocalMailbox.email
            ).exists()
            row = (
                s.query(LocalMailbox)
                .filter(LocalMailbox.status == 0)
                .filter(~used)
                .order_by(LocalMailbox.id.asc())
                .with_for_update()
                .first()
            )
            if row:
                row.status = 1
                return row.to_dict()
            return None

    def update_mailbox_status(self, email: str, status: int) -> None:
        with self.session() as s:
            s.query(LocalMailbox).filter_by(email=email).update(
                {"status": status}, synchronize_session=False
            )

    # --- KV operations ---

    def set_kv(self, key: str, value: Any) -> None:
        with self.session() as s:
            existing = s.query(SystemKV).filter_by(key=key).first()
            v = json.dumps(value, ensure_ascii=False)
            if existing:
                existing.value = v
            else:
                s.add(SystemKV(key=key, value=v))

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self.session() as s:
            row = s.query(SystemKV).filter_by(key=key).first()
            if row and row.value:
                try:
                    return json.loads(row.value)
                except json.JSONDecodeError:
                    return row.value
            return default


# Global singleton
db = DatabaseManager()
