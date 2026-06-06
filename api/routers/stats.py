from fastapi import APIRouter, Depends
from db import get_db
from models import Stats

router = APIRouter(prefix="/v1/stats", tags=["stats"])

@router.get("", response_model=Stats)
def get_stats(db = Depends(get_db)):
    db.execute("SELECT COUNT(*) FROM eh_galleries")
    total = db.fetchone()[0]

    db.execute("SELECT category, COUNT(*) FROM eh_galleries GROUP BY category")
    by_category = {row[0]: row[1] for row in db.fetchall() if row[0]}

    db.execute("SELECT MAX(last_synced_at) FROM eh_galleries")
    last_synced = db.fetchone()[0]

    return Stats(
        total_galleries=total,
        by_category=by_category,
        last_synced_at=last_synced,
    )
