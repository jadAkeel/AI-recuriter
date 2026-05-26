import aiosqlite
import asyncio
import json

COPY_DB = r"C:\Users\10User\Desktop\NLP - Copy\backend\app.db"
TARGET_DB = r"C:\Users\10User\Desktop\NLPFInalVersion\backend\app.db"

async def main():
    """
    Runs this script from the command line.
    """
    copy = await aiosqlite.connect(COPY_DB)
    target = await aiosqlite.connect(TARGET_DB)

    # Get candidates from copy
    cur = await copy.execute("SELECT * FROM candidates")
    cols = [d[0] for d in cur.description]
    rows = await cur.fetchall()
    print(f"Found {len(rows)} candidates in copy")

    for row in rows:
        data = dict(zip(cols, row))
        # Check if already exists in target
        cur2 = await target.execute(
            "SELECT id FROM candidates WHERE id = ?", (data["id"],)
        )
        if await cur2.fetchone():
            print(f"  Skipping {data['id']} (exists)")
            continue

        placeholders = ", ".join("?" for _ in cols)
        columns = ", ".join(cols)
        await target.execute(
            f"INSERT INTO candidates ({columns}) VALUES ({placeholders})",
            list(data.values())
        )
        print(f"  Copied {data['id']}: {data.get('full_name', '?')}")

    await target.commit()
    await copy.close()
    await target.close()
    print("Done!")

asyncio.run(main())
