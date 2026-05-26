import asyncio
from backend.app.core.db import get_db_session
from backend.app.models.user import User
from backend.app.services.auth import hash_password
from sqlalchemy import select

async def fix():
    """
    Updates the local test user password helper.
    """
    async for session in get_db_session():
        result = await session.execute(select(User).where(User.email == 'jadakeel05@gmail.com'))
        user = result.scalar_one()
        user.password_hash = hash_password('admin123')
        await session.commit()
        print('Password changed to: admin123')
        break

asyncio.run(fix())
