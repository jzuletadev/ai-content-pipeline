import logging
from .db import get_conn
from .youtube import build_client, search_channels, get_channel_details

logger = logging.getLogger(__name__)

# Keywords para descubrir canales de contenido IA.
# Ampliar o editar según los nichos que querés vigilar.
SEARCH_KEYWORDS = [
    # Originales
    "AI story animated",
    "AI generated story channel",
    "lyric video AI",
    "historia animada inteligencia artificial",
    "lyric video español",
    "video letra animado",
    "animated love story AI",
    # Entretenimiento animado / infantil IA
    "circo animado IA",
    "dibujos animados inteligencia artificial",
    "cuentos animados IA canal",
    "AI animated kids stories",
    "historias infantiles IA",
    # Historias bíblicas / religiosas IA
    "historias bíblicas inteligencia artificial",
    "cuentos bíblicos animados IA",
    "AI bible stories animated",
    "biblia animada IA canal",
    "religious AI animated stories",
    # Historias históricas / educativas IA
    "historia animada educativa IA",
    "AI historical stories channel",
    "hechos históricos animados IA",
    "AI educational stories Spanish",
    # Lyric videos en español (ampliar)
    "letras animadas canciones español",
    "lyrics video animado español canal",
    "letra canción animada IA",
    "AI lyrics video channel Spanish",
    # Historias de amor / drama IA
    "historia de amor animada IA",
    "AI love story channel Spanish",
    "drama animado inteligencia artificial",
    "romance animado IA canal",
]


def run():
    logger.info("channel_scraper: start")
    client = build_client()

    all_ids: set[str] = set()
    for keyword in SEARCH_KEYWORDS:
        logger.info(f"  search: {keyword!r}")
        try:
            ids = search_channels(client, keyword)
            all_ids.update(ids)
            logger.info(f"  → {len(ids)} channels")
        except Exception as e:
            logger.warning(f"  search failed for {keyword!r}: {e}")

    logger.info(f"Total unique channels found: {len(all_ids)}")

    channel_list = list(all_ids)
    for i in range(0, len(channel_list), 50):
        batch = channel_list[i : i + 50]
        try:
            items = get_channel_details(client, batch)
            _upsert_channels(items)
        except Exception as e:
            logger.error(f"Batch fetch/upsert failed: {e}")

    logger.info("channel_scraper: done")


def _upsert_channels(items: list[dict]):
    with get_conn() as conn:
        cur = conn.cursor()
        for item in items:
            snippet = item.get("snippet", {})
            cur.execute(
                """
                INSERT INTO channels (platform, platform_id, handle, title)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (platform, platform_id) DO UPDATE
                    SET title  = EXCLUDED.title,
                        handle = EXCLUDED.handle
                """,
                (
                    "youtube",
                    item["id"],
                    snippet.get("customUrl"),
                    snippet.get("title"),
                ),
            )
        logger.info(f"Upserted {len(items)} channels")
