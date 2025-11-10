"""Database-oriented services providing safe access patterns for models."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Optional, Sequence, Tuple, TypeVar

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import models


T = TypeVar("T")


class DatabaseServiceError(RuntimeError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "عملیات پایگاه داده با خطا مواجه شد.") -> None:
        super().__init__(message)


class EntityNotFoundError(DatabaseServiceError):
    """Raised when an expected entity cannot be located."""

    def __init__(self, entity_name: str, identifier: object) -> None:
        message = f"{entity_name} با شناسه {identifier} یافت نشد."
        super().__init__(message)
        self.entity_name = entity_name
        self.identifier = identifier


class SessionBackedService:
    """Base class providing error-handled session interactions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        return self._session

    def _execute(self, operation: Callable[[Session], T], *, commit: bool = False) -> T:
        try:
            result = operation(self._session)
            if commit:
                self._session.commit()
            return result
        except DatabaseServiceError:
            self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            self._session.rollback()
            raise DatabaseServiceError() from exc
        except Exception as exc:  # pragma: no cover - defensive programming
            self._session.rollback()
            raise DatabaseServiceError() from exc


class AdminUserService(SessionBackedService):
    """Encapsulate queries related to administrative users."""

    def get_by_username(self, username: str) -> models.AdminUser | None:
        return self._execute(
            lambda session: session.query(models.AdminUser)
            .filter_by(username=username)
            .first()
        )

    def ensure_default_admin(
        self,
        *,
        username: str = "admin",
        password_hash: str,
        role: models.AdminRole = models.AdminRole.SUPERADMIN,
    ) -> models.AdminUser:
        def operation(session: Session) -> models.AdminUser:
            user = session.query(models.AdminUser).filter_by(username=username).first()
            if user:
                return user
            default_user = models.AdminUser(
                username=username,
                password_hash=password_hash,
                role=role,
            )
            session.add(default_user)
            session.flush()
            return default_user

        return self._execute(operation, commit=True)


class JobQueryService(SessionBackedService):
    """Read helpers for job entities."""

    def list_recent_jobs(self, *, limit: Optional[int] = None) -> Sequence[models.Job]:
        def operation(session: Session) -> Sequence[models.Job]:
            query = session.query(models.Job).order_by(models.Job.created_at.desc())
            if limit is not None:
                query = query.limit(limit)
            return query.all()

        return self._execute(operation)


class SocialAccountService(SessionBackedService):
    """CRUD helpers for social accounts."""

    def list_accounts_desc(self) -> Sequence[models.SocialAccount]:
        return self._execute(
            lambda session: session.query(models.SocialAccount)
            .order_by(models.SocialAccount.created_at.desc())
            .all()
        )

    def get_account(self, account_id: int) -> models.SocialAccount | None:
        return self._execute(lambda session: session.get(models.SocialAccount, account_id))

    def save_account(
        self,
        *,
        account_id: Optional[int],
        data: dict[str, Optional[str]],
    ) -> Tuple[models.SocialAccount, bool]:
        def operation(session: Session) -> Tuple[models.SocialAccount, bool]:
            created = False
            if account_id is not None:
                account = session.get(models.SocialAccount, account_id)
                if account is None:
                    raise EntityNotFoundError("حساب کاربری", account_id)
            else:
                account = models.SocialAccount()
                session.add(account)
                created = True
            for field, value in data.items():
                setattr(account, field, value)
            session.flush()
            return account, created

        return self._execute(operation, commit=True)

    def delete_account(self, account_id: int) -> bool:
        def operation(session: Session) -> bool:
            account = session.get(models.SocialAccount, account_id)
            if account is None:
                return False
            session.delete(account)
            session.flush()
            return True

        return self._execute(operation, commit=True)


class ServiceTokenService(SessionBackedService):
    """Manage service token entities."""

    def list_tokens(self) -> Sequence[models.ServiceToken]:
        return self._execute(
            lambda session: session.query(models.ServiceToken)
            .order_by(models.ServiceToken.created_at.desc())
            .all()
        )

    def upsert_token(
        self,
        *,
        name: str,
        key: str,
        value: str,
        endpoint_url: str | None,
    ) -> Tuple[models.ServiceToken, bool]:
        def operation(session: Session) -> Tuple[models.ServiceToken, bool]:
            token = session.query(models.ServiceToken).filter_by(key=key).first()
            created = False
            if token:
                token.name = name
                token.value = value
                token.endpoint_url = endpoint_url
            else:
                token = models.ServiceToken(
                    name=name,
                    key=key,
                    value=value,
                    endpoint_url=endpoint_url,
                )
                session.add(token)
                created = True
            session.flush()
            return token, created

        return self._execute(operation, commit=True)

    def delete_token(self, token_id: int) -> bool:
        def operation(session: Session) -> bool:
            token = session.get(models.ServiceToken, token_id)
            if token is None:
                return False
            session.delete(token)
            session.flush()
            return True

        return self._execute(operation, commit=True)


class ScheduledPostService(SessionBackedService):
    """Operations for scheduled posts."""

    def list_recent_posts(self, *, limit: Optional[int] = None) -> Sequence[models.ScheduledPost]:
        def operation(session: Session) -> Sequence[models.ScheduledPost]:
            query = session.query(models.ScheduledPost).order_by(
                models.ScheduledPost.scheduled_time.desc()
            )
            if limit is not None:
                query = query.limit(limit)
            return query.all()

        return self._execute(operation)

    def create_post(
        self,
        *,
        account_id: int,
        title: str,
        content: Optional[str],
        video_url: Optional[str],
        scheduled_time: datetime,
    ) -> models.ScheduledPost:
        def operation(session: Session) -> models.ScheduledPost:
            post = models.ScheduledPost(
                account_id=account_id,
                title=title,
                content=content,
                video_url=video_url,
                scheduled_time=scheduled_time,
            )
            session.add(post)
            session.flush()
            return post

        return self._execute(operation, commit=True)

    def delete_post(self, post_id: int) -> bool:
        def operation(session: Session) -> bool:
            post = session.get(models.ScheduledPost, post_id)
            if post is None:
                return False
            session.delete(post)
            session.flush()
            return True

        return self._execute(operation, commit=True)


__all__ = [
    "AdminUserService",
    "DatabaseServiceError",
    "EntityNotFoundError",
    "JobQueryService",
    "ScheduledPostService",
    "ServiceTokenService",
    "SocialAccountService",
]
