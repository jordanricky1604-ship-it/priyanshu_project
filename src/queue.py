import asyncio
import aiosqlite
import json
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from datetime import datetime

logger = logging.getLogger("captcha_worker")

class CaptchaJob(BaseModel):
    id: int
    url: str
    status: str
    captcha_type: Optional[str] = None
    solution_token: Optional[str] = None
    cookies: Optional[str] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str

class JobQueue:
    def __init__(self, db_path: str = "queue.db"):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    captcha_type TEXT,
                    solution_token TEXT,
                    cookies TEXT,
                    error TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()

    async def enqueue(self, url: str) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO jobs (url, status) VALUES (?, ?)",
                (url, 'PENDING')
            )
            await db.commit()
            return cursor.lastrowid

    async def dequeue(self) -> Optional[CaptchaJob]:
        async with aiosqlite.connect(self.db_path) as db:
            # Atomic dequeue using SQLite UPDATE with RETURNING is not widely supported in old sqlite
            # We use a select then update strategy, locking if necessary (SQLite handles basic locking)
            
            cursor = await db.execute(
                "SELECT id, url, status, captcha_type, solution_token, cookies, error, created_at, updated_at "
                "FROM jobs WHERE status = 'PENDING' ORDER BY created_at ASC LIMIT 1"
            )
            row = await cursor.fetchone()
            if not row:
                return None

            job_id = row[0]
            await db.execute(
                "UPDATE jobs SET status = 'PROCESSING', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (job_id,)
            )
            await db.commit()

            return CaptchaJob(
                id=row[0],
                url=row[1],
                status='PROCESSING',
                captcha_type=row[3],
                solution_token=row[4],
                cookies=row[5],
                error=row[6],
                created_at=row[7],
                updated_at=row[8]
            )

    async def complete_job(self, job_id: int, captcha_type: str, solution_token: str, cookies: str = None):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET status = 'COMPLETED', captcha_type = ?, solution_token = ?, cookies = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (captcha_type, solution_token, cookies, job_id)
            )
            await db.commit()

    async def fail_job(self, job_id: int, error: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET status = 'FAILED', error = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (error, job_id)
            )
            await db.commit()

    async def get_job(self, job_id: int) -> Optional[CaptchaJob]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, url, status, captcha_type, solution_token, cookies, error, created_at, updated_at "
                "FROM jobs WHERE id = ?",
                (job_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return CaptchaJob(
                id=row[0],
                url=row[1],
                status=row[2],
                captcha_type=row[3],
                solution_token=row[4],
                cookies=row[5],
                error=row[6],
                created_at=row[7],
                updated_at=row[8]
            )
