from fastapi import APIRouter, Depends
from db import get_db
from models import Stats
from typing import Dict, Any

router = APIRouter(prefix="/v1/stats", tags=["stats"])

@router.get("", response_model=Stats)
def get_stats(db = Depends(get_db)):
    # Total count
    db.execute("SELECT COUNT(*) FROM eh_galleries")
    total = db.fetchone()[0]
    
    # By category
    db.execute("SELECT category, COUNT(*) FROM eh_galleries GROUP BY category")
    by_category = {row[0]: row[1] for row in db.fetchall() if row[0]}
    
    # Last synced
    db.execute("SELECT MAX(last_synced_at) FROM eh_galleries")
    last_synced = db.fetchone()[0]
    
    # Queue status
    db.execute("SELECT job_name, state, last_run_at FROM schedule_state")
    queue_status = {}
    for row in db.fetchall():
        queue_status[row[0]] = {
            "state": row[1],
            "last_run_at": row[2]
        }
        
    return Stats(
        total_galleries=total,
        by_category=by_category,
        last_synced_at=last_synced,
        queue_status=queue_status
    )
