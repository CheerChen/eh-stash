from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime

class Gallery(BaseModel):
    gid: int
    token: str
    category: Optional[str] = None
    title: Optional[str] = None
    title_jpn: Optional[str] = None
    uploader: Optional[str] = None
    posted_at: Optional[datetime] = None # Or string? DB has TIMESTAMPTZ, psycopg2 returns datetime
    language: Optional[str] = None
    pages: Optional[int] = None
    rating: Optional[float] = None
    fav_count: Optional[int] = 0
    comment_count: Optional[int] = 0
    thumb: Optional[str] = None
    tags: Optional[Dict[str, List[str]]] = None
    last_synced_at: Optional[datetime] = None
    is_active: bool = True

class GalleryList(BaseModel):
    items: List[Gallery]
    total: int
    page: int
    size: int
    pages: int  # total number of pages

class Stats(BaseModel):
    total_galleries: int
    by_category: Dict[str, int]
    last_synced_at: Optional[datetime] = None
    queue_status: Dict[str, Any]
