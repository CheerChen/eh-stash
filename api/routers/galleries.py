from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from db import get_db
from models import Gallery, GalleryList
import math
import os
import json

router = APIRouter(prefix="/v1/galleries", tags=["galleries"])

def _parse_blacklist() -> list[tuple[str, str]]:
    """Parse TAG_BLACKLIST env var.
    Format: "ns:value,ns:value,..."
    Returns list of (namespace, value) tuples.
    """
    raw = os.getenv("TAG_BLACKLIST", "")
    result = []
    for item in raw.split(","):
        item = item.strip()
        if ":" in item:
            ns, val = item.split(":", 1)
            result.append((ns.strip(), val.strip()))
    return result

TAG_BLACKLIST: list[tuple[str, str]] = _parse_blacklist()

@router.get("", response_model=GalleryList)
def get_galleries(
    category: Optional[str] = None,
    language: Optional[str] = None,
    min_rating: Optional[float] = None,
    min_fav: Optional[int] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "gid_desc",
    page: int = 1,
    page_size: int = 24,
    db = Depends(get_db)
):
    offset = (page - 1) * page_size
    
    query = "SELECT * FROM eh_galleries WHERE is_active = TRUE"
    params = []

    # Tag blacklist — each entry adds: AND NOT (tags @> '{"ns": ["val"]}'::jsonb)
    for ns, val in TAG_BLACKLIST:
        query += " AND NOT (tags @> %s::jsonb)"
        params.append(json.dumps({ns: [val]}))

    if category:
        query += " AND category ILIKE %s"
        params.append(category)
    if language:
        query += " AND language ILIKE %s"
        params.append(language)
    if min_rating is not None:
        query += " AND rating >= %s"
        params.append(min_rating)
    if min_fav is not None:
        query += " AND fav_count >= %s"
        params.append(min_fav)
    if tag:
        # Normalize tag input (handle full-width colon and extra spaces)
        tag = tag.replace("：", ":").strip()
        if tag:
            # tag format: namespace:value
            if ":" in tag:
                ns, val = tag.split(":", 1)
                ns = ns.strip().lower()
                val = val.strip()
                if ns and val:
                    # tags is JSONB: {"namespace": ["value1", "value2"]}
                    # Use @> operator
                    query += " AND tags @> %s::jsonb"
                    params.append(json.dumps({ns: [val]}))
            else:
                # No namespace provided — ignore to keep behavior explicit
                pass

    # Sort
    if sort == "rating":
        query += " ORDER BY rating DESC NULLS LAST"
    elif sort == "posted_at":
        query += " ORDER BY posted_at DESC NULLS LAST"
    elif sort == "fav_count":
        query += " ORDER BY fav_count DESC NULLS LAST"
    elif sort == "gid_asc":
        query += " ORDER BY gid ASC"
    else:  # default gid_desc to avoid global popularity ordering
        query += " ORDER BY gid DESC"
    
    # Pagination
    count_query = f"SELECT COUNT(*) FROM ({query}) AS sub"
    db.execute(count_query, params)
    total = db.fetchone()[0]
    
    query += " LIMIT %s OFFSET %s"
    params.extend([page_size, offset])
    
    db.execute(query, params)
    rows = db.fetchall()
    
    # Convert rows to dicts
    # We need column names
    col_names = [desc[0] for desc in db.description]
    items = []
    for row in rows:
        item = dict(zip(col_names, row))
        items.append(Gallery(**item))
        
    return GalleryList(items=items, total=total, page=page, size=page_size, pages=math.ceil(total / page_size) if total else 0)

@router.get("/{gid}", response_model=Gallery)
def get_gallery(gid: int, db = Depends(get_db)):
    db.execute("SELECT * FROM eh_galleries WHERE gid = %s", (gid,))
    row = db.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Gallery not found")
    
    col_names = [desc[0] for desc in db.description]
    item = dict(zip(col_names, row))
    return Gallery(**item)
