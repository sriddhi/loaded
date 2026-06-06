#!/usr/bin/env python3
"""
Standalone admin seeder.

Usage:
    cd backend && python ../scripts/seed_admin.py

Reads DATABASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD from environment (or .env).
Creates the admin user if not already present.
"""

import asyncio
import os
import sys

# Load .env from backend directory
from pathlib import Path

env_file = Path(__file__).parent.parent / "backend" / ".env"
if env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(env_file)


async def main() -> None:
    db_url = os.getenv("DATABASE_URL")
    email = os.getenv("ADMIN_EMAIL")
    password = os.getenv("ADMIN_PASSWORD")

    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)
    if not email or not password:
        print("ERROR: ADMIN_EMAIL and ADMIN_PASSWORD must be set", file=sys.stderr)
        sys.exit(1)

    import asyncpg

    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.auth.db import create_user, get_user_by_email
    from app.auth.security import hash_password

    conn = await asyncpg.connect(db_url)
    try:
        existing = await get_user_by_email(conn, email)
        if existing:
            print(f"Admin already exists: {email}")
        else:
            await create_user(conn, email, hash_password(password), role="admin")
            print(f"Admin created: {email}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
