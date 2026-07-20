import os
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from .db import get_conn

VALID_STATUSES = {"review", "approved", "rejected", "published"}

app = FastAPI()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.get("/", response_class=HTMLResponse)
def index(request: Request, status: str = "review"):
    if status not in VALID_STATUSES:
        status = "review"
    videos = _load_videos(status)
    return templates.TemplateResponse(request, "index.html", {
        "videos": videos,
        "current_status": status,
    })


@app.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(request: Request, video_id: int):
    video = _load_video(video_id)
    if not video:
        raise HTTPException(404, "Video no encontrado")
    return templates.TemplateResponse(request, "video.html", {"video": video})


@app.get("/videos/{video_id}/file")
def video_file(video_id: int):
    video = _load_video(video_id)
    if not video or not video["render_path"]:
        raise HTTPException(404, "Render no encontrado")
    path = Path(video["render_path"])
    if not path.exists():
        raise HTTPException(404, "Archivo no encontrado en disco")
    return FileResponse(path, media_type="video/mp4", filename=f"video_{video_id}.mp4")


@app.post("/videos/{video_id}/approve")
def approve(video_id: int):
    _update_status(video_id, "approved")
    return RedirectResponse(f"/videos/{video_id}", status_code=303)


@app.post("/videos/{video_id}/reject")
def reject(video_id: int):
    _update_status(video_id, "rejected")
    return RedirectResponse(f"/videos/{video_id}", status_code=303)


@app.post("/videos/{video_id}/published")
def published(video_id: int, published_url: str = Form(...)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE videos
            SET status = 'published', published_at = now(), published_url = %s
            WHERE id = %s
            """,
            (published_url.strip(), video_id),
        )
    return RedirectResponse(f"/videos/{video_id}", status_code=303)


def _load_videos(status: str) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, v.status, v.metadata, v.created_at, ac.name AS channel_name
            FROM videos v
            LEFT JOIN active_channels ac ON ac.id = v.active_channel_id
            WHERE v.status = %s
            ORDER BY v.created_at DESC
        """, (status,))
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _load_video(video_id: int) -> dict | None:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT v.id, v.status, v.metadata, v.render_path, v.created_at, v.published_at,
                   v.published_url, ac.name AS channel_name
            FROM videos v
            LEFT JOIN active_channels ac ON ac.id = v.active_channel_id
            WHERE v.id = %s
        """, (video_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def _update_status(video_id: int, status: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE videos SET status = %s WHERE id = %s", (status, video_id))
