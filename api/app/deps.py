"""Request dependencies."""

from __future__ import annotations

import uuid

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import AnonUser
from app.settings import settings

COOKIE_NAME = "ccse_anon"
COOKIE_MAX_AGE = 60 * 60 * 24 * 180


async def current_anon(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> uuid.UUID:
    """Return the anonymous user id, creating and setting the cookie if needed.

    No accounts, no PII: the id only exists to keep attempts together.
    """
    raw = request.cookies.get(COOKIE_NAME)
    anon_id: uuid.UUID | None = None
    if raw:
        try:
            anon_id = uuid.UUID(raw)
        except ValueError:
            anon_id = None

    if anon_id is not None and await session.get(AnonUser, anon_id) is not None:
        return anon_id

    anon_id = uuid.uuid4()
    session.add(AnonUser(id=anon_id))
    await session.commit()
    response.set_cookie(
        COOKIE_NAME,
        str(anon_id),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return anon_id
