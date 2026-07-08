import asyncio
import logging
import argparse
from typing import Optional

from src.queue import JobQueue
from src.router import StrategyRouter
from src.config import get_config
from src.utils.model_manager import ModelManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("worker")


async def run_worker(db_path: str = "queue.db", poll_interval: int = 5):
    queue = JobQueue(db_path=db_path)
    await queue.init_db()
    
    config = get_config()
    # Force headless for the worker so it doesn't pop up windows
    config.solver.browser_headless = True
    
    logger.info("Initializing models for background worker...")
    model_manager = ModelManager(
        whisper_model_size=config.solver.audio_model_size,
        clip_model_name=config.solver.clip_model_name
    )
    
    logger.info("Initializing Playwright and Router...")
    from playwright.async_api import async_playwright
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(headless=config.solver.browser_headless)
    # Pass model_manager to config.solver so solvers can use it
    config.solver.model_manager = model_manager
    router = StrategyRouter(config=config.solver, browser=browser)
    logger.info(f"Worker started. Polling {db_path} every {poll_interval}s...")
    
    try:
        while True:
            job = await queue.dequeue()
            if not job:
                await asyncio.sleep(poll_interval)
                continue
            
            logger.info(f"Processing job {job.id} for URL: {job.url}")
            try:
                # The router expects to be passed the url via solve
                solution = await router.solve(page_url=job.url)
                
                if solution.success:
                    logger.info(f"Job {job.id} SUCCESS: {solution.type.name} solved.")
                    # Use json.dumps to stringify cookies dict for sqlite
                    import json
                    await queue.complete_job(job.id, solution.type.name, solution.token, json.dumps(solution.cookies))
                else:
                    logger.warning(f"Job {job.id} FAILED: {solution.error}")
                    await queue.fail_job(job.id, str(solution.error))
                    
            except Exception as e:
                logger.error(f"Job {job.id} CRASHED: {e}")
                await queue.fail_job(job.id, str(e))
                
    except asyncio.CancelledError:
        logger.info("Worker shutting down...")
    finally:
        pass

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the CAPTCHA solver background worker.")
    parser.add_argument("--db", type=str, default="queue.db", help="Path to SQLite queue DB")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    args = parser.parse_args()
    
    asyncio.run(run_worker(db_path=args.db, poll_interval=args.interval))
