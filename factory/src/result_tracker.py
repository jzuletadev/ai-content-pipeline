import logging
import os
import re
from googleapiclient.discovery import build
from .db import get_conn

logger = logging.getLogger(__name__)

YOUTUBE_ID_PATTERNS = [
    r"(?:youtube\.com/watch\?v=|youtube\.com/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})",
]


def run():
    logger.info("result_tracker: start")
    videos = _load_published_videos()
    if not videos:
        logger.info("Sin videos publicados con URL para trackear")
        return

    client = build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])

    # Batch de a 50 (límite de la API)
    for i in range(0, len(videos), 50):
        batch = videos[i : i + 50]
        yt_id_to_video = {}
        for v in batch:
            yt_id = _extract_youtube_id(v["published_url"])
            if yt_id:
                yt_id_to_video[yt_id] = v["id"]
            else:
                logger.warning(f"No se pudo extraer ID de YouTube de: {v['published_url']!r}")

        if not yt_id_to_video:
            continue

        try:
            resp = client.videos().list(
                id=",".join(yt_id_to_video.keys()),
                part="statistics",
                maxResults=50,
            ).execute()
        except Exception as e:
            logger.error(f"YouTube API falló: {e}")
            continue

        for item in resp.get("items", []):
            video_id = yt_id_to_video.get(item["id"])
            if video_id is None:
                continue
            stats = item.get("statistics", {})
            _save_result(video_id, stats)

    logger.info("result_tracker: done")


def _extract_youtube_id(url: str) -> str | None:
    for pattern in YOUTUBE_ID_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _load_published_videos() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT id, published_url
            FROM videos
            WHERE status = 'published' AND published_url IS NOT NULL
        """)
        return [{"id": row[0], "published_url": row[1]} for row in cur.fetchall()]


def _save_result(video_id: int, stats: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO video_results (video_id, views, likes, comments, shares)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                video_id,
                int(stats.get("viewCount") or 0),
                int(stats.get("likeCount") or 0),
                int(stats.get("commentCount") or 0),
                0,  # shares no disponible por API
            ),
        )
        logger.info(f"  Video {video_id}: {stats.get('viewCount', 0)} views")
