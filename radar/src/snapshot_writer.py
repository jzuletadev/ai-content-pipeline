import logging
import isodate
from datetime import datetime
from .db import get_conn
from .youtube import build_client, get_channel_details, get_recent_video_ids, get_video_details

logger = logging.getLogger(__name__)


def run():
    logger.info("snapshot_writer: start")
    client = build_client()

    rows = _load_channels()
    logger.info(f"Channels to snapshot: {len(rows)}")

    for i in range(0, len(rows), 50):
        batch = rows[i : i + 50]
        platform_ids = [r[1] for r in batch]
        db_id_by_platform = {r[1]: r[0] for r in batch}

        try:
            items = get_channel_details(client, platform_ids)
        except Exception as e:
            logger.error(f"channels.list failed: {e}")
            continue

        for item in items:
            db_id = db_id_by_platform.get(item["id"])
            if db_id is None:
                continue

            try:
                _save_snapshot(db_id, item)
            except Exception as e:
                logger.error(f"Snapshot save failed for {item['id']}: {e}")

            try:
                _save_recent_videos(client, db_id, item)
            except Exception as e:
                logger.error(f"Video save failed for {item['id']}: {e}")

    logger.info("snapshot_writer: done")


def _load_channels() -> list[tuple[int, str]]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, platform_id FROM channels WHERE platform = 'youtube'")
        return cur.fetchall()


def _save_snapshot(channel_db_id: int, item: dict):
    stats = item.get("statistics", {})
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO channel_snapshots (channel_id, subscribers, total_views, video_count)
            VALUES (%s, %s, %s, %s)
            """,
            (
                channel_db_id,
                int(stats.get("subscriberCount") or 0),
                int(stats.get("viewCount") or 0),
                int(stats.get("videoCount") or 0),
            ),
        )


def _save_recent_videos(client, channel_db_id: int, channel_item: dict):
    uploads = (
        channel_item.get("contentDetails", {})
        .get("relatedPlaylists", {})
        .get("uploads")
    )
    if not uploads:
        return

    video_ids = get_recent_video_ids(client, uploads)
    if not video_ids:
        return

    videos = get_video_details(client, video_ids)

    with get_conn() as conn:
        cur = conn.cursor()
        for v in videos:
            stats = v.get("statistics", {})
            snippet = v.get("snippet", {})
            content = v.get("contentDetails", {})

            duration_sec = None
            if content.get("duration"):
                try:
                    duration_sec = int(
                        isodate.parse_duration(content["duration"]).total_seconds()
                    )
                except Exception:
                    pass

            published_at = None
            if snippet.get("publishedAt"):
                published_at = datetime.fromisoformat(
                    snippet["publishedAt"].replace("Z", "+00:00")
                )

            cur.execute(
                """
                INSERT INTO observed_videos
                    (channel_id, platform_id, title, published_at, duration_sec,
                     views, likes, comments)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (platform_id, captured_at) DO NOTHING
                """,
                (
                    channel_db_id,
                    v["id"],
                    snippet.get("title"),
                    published_at,
                    duration_sec,
                    int(stats.get("viewCount") or 0),
                    int(stats.get("likeCount") or 0),
                    int(stats.get("commentCount") or 0),
                ),
            )
        logger.info(f"Saved {len(videos)} videos for channel {channel_db_id}")
