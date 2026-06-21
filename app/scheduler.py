"""Scheduled tasks for periodic maintenance and reporting."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.memory.consolidate import consolidate

log = logging.getLogger("nexus.scheduler")

_SCHEDULER_KEY = "nexus:scheduler:last_run"
_REPORT_KEY = "nexus:scheduler:last_report"


async def generate_consolidation_report(db: AsyncSession) -> dict:
    """Generate a detailed report of memory system health and consolidation results."""
    try:
        # Get overall memory statistics
        total_memories = (await db.execute(text("SELECT COUNT(*) FROM memories"))).scalar() or 0
        total_agents = (await db.execute(text("SELECT COUNT(*) FROM agents"))).scalar() or 0
        total_entities = (await db.execute(text("SELECT COUNT(*) FROM entities"))).scalar() or 0
        
        # Get memory type distribution
        type_dist = await db.execute(text("""
            SELECT memory_type, COUNT(*) as count
            FROM memories
            GROUP BY memory_type
            ORDER BY count DESC
        """))
        by_type = {row.memory_type: row.count for row in type_dist.fetchall()}
        
        # Get importance distribution
        high_importance = (await db.execute(text("""
            SELECT COUNT(*) FROM memories WHERE importance >= 0.7
        """))).scalar() or 0
        
        low_importance = (await db.execute(text("""
            SELECT COUNT(*) FROM memories WHERE importance < 0.3
        """))).scalar() or 0
        
        # Get agent activity (last 24h)
        active_agents = (await db.execute(text("""
            SELECT COUNT(*) FROM agents 
            WHERE last_active > NOW() - INTERVAL '24 hours'
        """))).scalar() or 0
        
        # Get recent memory growth (last 7 days)
        recent_growth = (await db.execute(text("""
            SELECT COUNT(*) FROM memories 
            WHERE created_at > NOW() - INTERVAL '7 days'
        """))).scalar() or 0
        
        # Get consolidation history from Redis if available
        recent_consolidations = []
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "memory_stats": {
                "total_memories": total_memories,
                "total_agents": total_agents,
                "total_entities": total_entities,
                "by_type": by_type,
                "high_importance": high_importance,
                "low_importance": low_importance,
            },
            "activity_stats": {
                "active_agents_24h": active_agents,
                "recent_growth_7d": recent_growth,
            },
            "consolidation_history": recent_consolidations,
        }
    except Exception as e:
        log.error("Failed to generate consolidation report: %s", e)
        return {"error": str(e), "timestamp": datetime.now(timezone.utc).isoformat()}


async def run_daily_consolidation():
    """Run daily consolidation and generate report (scheduled for 3am)."""
    log.info("Starting daily consolidation and reporting")
    
    async with SessionLocal() as db:
        # Run consolidation
        stats = await consolidate(db)
        log.info("Daily consolidation completed: %s", stats)
        
        # Generate report
        report = await generate_consolidation_report(db)
        report["consolidation_stats"] = stats
        
        # Store report in Redis for dashboard access
        try:
            redis_client = aioredis.from_url(settings.redis_url)
            await redis_client.setex(_REPORT_KEY, 86400, str(report))  # Keep for 24 hours
            await redis_client.aclose()
        except Exception as e:
            log.warning("Failed to store report in Redis: %s", e)
        
        log.info("Daily consolidation report generated: %d memories, %d agents", 
                 report.get("memory_stats", {}).get("total_memories", 0),
                 report.get("memory_stats", {}).get("total_agents", 0))
        
        return report


async def should_run_daily() -> bool:
    """Check if daily consolidation should run (based on last run time)."""
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        last_run = await redis_client.get(_SCHEDULER_KEY)
        await redis_client.aclose()
        
        if not last_run:
            return True
        
        # Check if last run was more than 20 hours ago
        from datetime import timedelta
        last_run_time = datetime.fromisoformat(last_run.decode())
        return datetime.now(timezone.utc) - last_run_time > timedelta(hours=20)
    except Exception as e:
        log.warning("Failed to check last run time: %s", e)
        return True  # Run if we can't determine


async def mark_daily_run():
    """Mark that daily consolidation has been run."""
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        await redis_client.setex(_SCHEDULER_KEY, 86400, datetime.now(timezone.utc).isoformat())
        await redis_client.aclose()
    except Exception as e:
        log.warning("Failed to mark daily run: %s", e)


async def get_latest_report() -> Optional[dict]:
    """Get the most recent consolidation report from Redis."""
    try:
        redis_client = aioredis.from_url(settings.redis_url)
        report_data = await redis_client.get(_REPORT_KEY)
        await redis_client.aclose()
        
        if report_data:
            import json
            return json.loads(report_data.decode())
        return None
    except Exception as e:
        log.warning("Failed to get latest report: %s", e)
        return None


async def scheduler_loop():
    """Background scheduler loop that runs daily consolidation at 3am."""
    log.info("Scheduler loop started")
    
    while True:
        try:
            # Check if it's 3am (within 1 hour window) and hasn't run today
            now = datetime.now(timezone.utc)
            hour = now.hour
            
            # Run between 2am-4am UTC (adjust for your timezone as needed)
            if 2 <= hour <= 4 and await should_run_daily():
                log.info("Running daily consolidation (scheduled window)")
                await run_daily_consolidation()
                await mark_daily_run()
            
            # Sleep for 1 hour between checks
            await asyncio.sleep(3600)
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Scheduler error: %s", e)
            await asyncio.sleep(3600)  # Sleep and retry
    
    log.info("Scheduler loop stopped")


# Simple worker function that can be called externally
async def run_scheduled_consolidation():
    """Manually trigger scheduled consolidation (for testing or external schedulers)."""
    if await should_run_daily():
        report = await run_daily_consolidation()
        await mark_daily_run()
        return report
    else:
        return {"message": "Daily consolidation already ran recently"}