import asyncio
from app.core.db import get_db_session
from app.models.user import User
from app.services.auth import hash_password
from sqlalchemy import select

async def fix():
    """
    Resets the local user's password for development access.
    """
    async for session in get_db_session():
        result = await session.execute(
            select(User).where(User.email == 'jadakeel05@gmail.com')
        )
        user = result.scalar_one()
        user.password_hash = hash_password('123')
        await session.commit()
        print('Password changed to: 123')
        break

asyncio.run(fix())
