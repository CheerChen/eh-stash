import os
from pathlib import Path
from typing import List
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from routers import admin, galleries, stats
from db import get_db
from models import PreferenceTag

THUMB_DIR = Path(os.getenv("THUMB_DIR", "/data/thumbs"))

app = FastAPI(title="EH-Stash API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(galleries.router)
app.include_router(stats.router)
app.include_router(admin.router)

@app.get("/v1/thumbs/{gid}")
async def get_thumb(gid: int):
    path = THUMB_DIR / str(gid)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Thumb not cached yet")
    return Response(
        content=path.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=604800"},  # 7 天
    )

@app.get("/")
def root():
    return {"message": "EH-Stash API is running"}

@app.get("/v1/preferences", response_model=List[PreferenceTag])
def get_preferences(db=Depends(get_db)):
    db.execute("SELECT namespace, tag, weight, count FROM preference_tags ORDER BY weight DESC")
    rows = db.fetchall()
    return [PreferenceTag(namespace=r[0], tag=r[1], weight=r[2], count=r[3]) for r in rows]
