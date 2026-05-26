"""Reset password helper."""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend'))

from app.core.db import get_db_session
from app.models.user import User
from app.services.auth import hash_password
from sqlalchemy import select


async def fix():
    """
    Updates the local test user password helper.
    """
    async for session in get_db_session():
        result = await session.execute(
            select(User).where(User.email == 'jadakeel05@gmail.com')
        )
        user = result.scalar_one()
        user.password_hash = hash_password('admin123')
        await session.commit()
        print('Password changed to: admin123')
        break


asyncio.run(fix())
