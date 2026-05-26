import aiosqlite
import asyncio

async def check():
    """
    Prints candidate and user rows from the local SQLite database.
    """
    db = await aiosqlite.connect('app.db')
    cur = await db.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = await cur.fetchall()
    print('Tables:', [t[0] for t in tables])
    
    cur = await db.execute("SELECT id, full_name, email FROM candidates")
    rows = await cur.fetchall()
    print(f'Candidates ({len(rows)}):')
    for r in rows:
        print(f'  {r[0]}: {r[1]} ({r[2]})')
    
    cur = await db.execute("SELECT id, email, role FROM users")
    rows = await cur.fetchall()
    print(f'Users ({len(rows)}):')
    for r in rows:
        print(f'  {r[0]}: {r[1]} ({r[2]})')
    await db.close()

asyncio.run(check())
