import logging
import os
import requests
from datetime import date
from .db import get_conn

logger = logging.getLogger(__name__)

LASTFM_API_URL = "https://ws.audioscrobbler.com/2.0/"

# Géneros de Last.fm con buena presencia latina
LASTFM_TAGS = ["latin", "reggaeton", "bachata", "latin pop", "salsa"]

# Países para geo.getTopTracks
LASTFM_COUNTRIES = ["mexico", "spain", "argentina", "colombia"]


def run():
    logger.info("topic_scraper: start")
    channels = _load_active_channels()

    if not channels:
        logger.warning("No hay active_channels en BD. Correr setup_channel.py primero.")
        return

    for ch in channels:
        niche = ch["niche_name"]
        logger.info(f"Scraping temas para canal '{ch['name']}' (nicho: {niche})")
        try:
            if niche == "lyric_videos":
                _scrape_lyric_topics(ch["id"])
            elif niche == "historias_historicas":
                _scrape_history_topics(ch["id"])
            else:
                logger.warning(f"Sin estrategia para nicho: {niche}")
        except Exception as e:
            logger.error(f"topic_scraper falló para canal {ch['id']}: {e}")

    logger.info("topic_scraper: done")


# ─── Lyric Videos ────────────────────────────────────────────────────────────

def _scrape_lyric_topics(channel_id: int):
    api_key = os.environ["LASTFM_API_KEY"]
    existing = _get_existing_refs(channel_id)
    new_topics = []

    # Tracks trending por país
    for country in LASTFM_COUNTRIES:
        try:
            tracks = _lastfm_geo_top_tracks(api_key, country)
            for track in tracks:
                ref = f"lastfm_{track['artist']['name']}_{track['name']}".lower().replace(" ", "_")
                if ref in existing:
                    continue
                new_topics.append({
                    "channel_id": channel_id,
                    "title": f"{track['name']} — {track['artist']['name']}",
                    "source_ref": ref,
                    "trend_score": _normalize_listeners(track.get("listeners", "0")),
                    "meta": {"artist": track["artist"]["name"], "song_title": track["name"]},
                })
                existing.add(ref)
        except Exception as e:
            logger.warning(f"Last.fm geo top tracks falló para {country}: {e}")

    # Tracks trending por género latino
    for tag in LASTFM_TAGS:
        try:
            tracks = _lastfm_tag_top_tracks(api_key, tag)
            for track in tracks:
                ref = f"lastfm_{track['artist']['name']}_{track['name']}".lower().replace(" ", "_")
                if ref in existing:
                    continue
                new_topics.append({
                    "channel_id": channel_id,
                    "title": f"{track['name']} — {track['artist']['name']}",
                    "source_ref": ref,
                    "trend_score": 0.5,
                    "meta": {"artist": track["artist"]["name"], "song_title": track["name"]},
                })
                existing.add(ref)
        except Exception as e:
            logger.warning(f"Last.fm tag top tracks falló para {tag}: {e}")

    new_topics.sort(key=lambda x: x["trend_score"], reverse=True)
    _insert_topics(new_topics[:5])
    logger.info(f"  lyric_videos: {len(new_topics[:5])} temas nuevos insertados")


def _lastfm_geo_top_tracks(api_key: str, country: str) -> list[dict]:
    resp = requests.get(LASTFM_API_URL, params={
        "method": "geo.getTopTracks",
        "country": country,
        "api_key": api_key,
        "format": "json",
        "limit": 10,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json().get("tracks", {}).get("track", [])


def _lastfm_tag_top_tracks(api_key: str, tag: str) -> list[dict]:
    resp = requests.get(LASTFM_API_URL, params={
        "method": "tag.getTopTracks",
        "tag": tag,
        "api_key": api_key,
        "format": "json",
        "limit": 10,
    }, timeout=10)
    resp.raise_for_status()
    return resp.json().get("tracks", {}).get("track", [])


def _normalize_listeners(listeners_str: str) -> float:
    try:
        n = int(listeners_str.replace(",", ""))
        return min(n / 5_000_000, 1.0)
    except Exception:
        return 0.5


# ─── Historias Históricas ─────────────────────────────────────────────────────

def _scrape_history_topics(channel_id: int):
    today = date.today()
    existing = _get_existing_refs(channel_id)
    new_topics = []

    try:
        resp = requests.get(
            f"https://es.wikipedia.org/api/rest_v1/feed/onthisday/events/{today.month}/{today.day}",
            timeout=10,
            headers={"User-Agent": "content-factory/1.0 (proyecto personal, uso educativo)"},
        )
        resp.raise_for_status()
        events = resp.json().get("events", [])

        for event in events[:10]:
            ref = f"wiki_{today.month}_{today.day}_{event.get('year', '')}"
            if ref in existing:
                continue

            text = event.get("text", "")
            year = event.get("year", "")
            title = f"{year}: {text[:80]}" if year else text[:80]

            new_topics.append({
                "channel_id": channel_id,
                "title": title,
                "source_ref": ref,
                "trend_score": 0.5,
                "meta": {"year": year, "description": text, "type": "on_this_day"},
            })
            existing.add(ref)
    except Exception as e:
        logger.warning(f"Wikipedia scrape falló: {e}")

    _insert_topics(new_topics[:3])
    logger.info(f"  historias_historicas: {len(new_topics[:3])} temas nuevos insertados")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _load_active_channels() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT ac.id, ac.name, ac.style_config, n.name AS niche_name
            FROM active_channels ac
            LEFT JOIN niches n ON n.id = ac.niche_id
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _get_existing_refs(channel_id: int) -> set[str]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT source_ref FROM topics WHERE active_channel_id = %s AND source_ref IS NOT NULL",
            (channel_id,),
        )
        return {row[0] for row in cur.fetchall()}


def _insert_topics(topics: list[dict]):
    if not topics:
        return
    with get_conn() as conn:
        cur = conn.cursor()
        for t in topics:
            cur.execute(
                """
                INSERT INTO topics (active_channel_id, title, source_ref, trend_score, status)
                VALUES (%s, %s, %s, %s, 'pending')
                ON CONFLICT DO NOTHING
                """,
                (t["channel_id"], t["title"], t["source_ref"], t["trend_score"]),
            )
