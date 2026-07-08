from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from src.queue import JobQueue
import uvicorn
import asyncio

app = FastAPI(title="CAPTCHA Solver API")
queue = JobQueue(db_path="queue.db")

class JobSubmit(BaseModel):
    url: str

@app.on_event("startup")
async def startup_event():
    await queue.init_db()

@app.post("/tasks", status_code=201)
async def create_task(job: JobSubmit):
    """Submit a URL to the CAPTCHA solver queue."""
    job_id = await queue.enqueue(job.url)
    return {"job_id": job_id, "status": "PENDING"}

@app.get("/tasks/{job_id}")
async def get_task(job_id: int):
    """Check the status of a specific CAPTCHA job."""
    job = await queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    
    return {
        "job_id": job.id,
        "url": job.url,
        "status": job.status,
        "captcha_type": job.captcha_type,
        "solution_token": job.solution_token,
        "cookies": job.cookies,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at
    }

if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=8000, reload=True)
