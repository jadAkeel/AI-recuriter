from __future__ import annotations

import argparse
import asyncio
import getpass

from app.core.db import SessionLocal, init_db
from app.services.auth import get_user_by_email, register_user, update_user_role


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a user role")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password")
    parser.add_argument("--full-name", default="Owner User")
    parser.add_argument("--role", default="owner", choices=["candidate", "recruiter", "admin", "owner"])
    args = parser.parse_args()
    password = args.password or getpass.getpass("Password: ")

    await init_db()

    async with SessionLocal() as session:
        user = await get_user_by_email(session, args.email)
        if user is None:
            user = await register_user(session, args.email, password, args.full_name)

        user = await update_user_role(session, user.id, args.role)
        print(f"OK: {user.email} role={user.role}")


if __name__ == "__main__":
    asyncio.run(main())
