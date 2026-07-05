"""Entry point for the nexus-worker container (background extraction + consolidation)."""

import asyncio
import logging
from app.memory.extract import run_worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

if __name__ == "__main__":
    asyncio.run(run_worker())
