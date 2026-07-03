import logging
from .db import get_conn

logger = logging.getLogger(__name__)

# Título contiene cualquiera de estas → is_ai_content = TRUE
AI_SIGNALS = [
    " ai ",
    " ia ",
    "ai story",
    "ai stories",
    "ia story",
    "ia stories",
    "ai generated",
    "ai animated",
    "ia animad",
    "historias ia",
    "historia ia",
    "relatos ia",
    "relatos ai",
    "inteligencia artificial",
    "artificial intelligence",
    "ai bible",
    "ai history",
    "ai historian",
    "ai historical",
    "ai relatos",
    "lyric ai",
    "ai lyrics",
    "ai lyric",
    "lyrics ai",
    "ai cuento",
    "ai cartoon",
    "ai horror",
    "horror ai",
    "creepypasta ai",
    "creepypasta ia",
    "ai love",
    "love ai",
    "anime ai",
    "ai anime",
    "ai fruit",
    "ai food",
    "ai kids",
    "ai church",
]

# Título contiene cualquiera de estas → is_ai_content = FALSE (no son contenido IA)
NON_AI_SIGNALS = [
    "nursery rhymes",
    "pinkfong",
    "bebefinn",
    "looloo",
    "chiki toonz",
    "canciones infantiles",
    "música infantil",
    "musica infantil",
    "tops de animes",
    "animes recap",
    "anime recap",
    "animes cada",
    "- topic",          # canales auto-generados YouTube Music
    "pocoyo",
    "sheriff labrador",
    "wild brain",
    "wildbrain",
    "cocomelon",
]


def run():
    logger.info("data_cleaner: start")

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title FROM channels WHERE title IS NOT NULL AND niche_guess != 'youtube_topic_channel'"
        )
        rows = cur.fetchall()

    ai_true = 0
    ai_false = 0
    skipped = 0

    with get_conn() as conn:
        cur = conn.cursor()
        for row_id, title in rows:
            t = title.lower()

            is_ai = _has_ai_signal(t)
            is_non_ai = _has_non_ai_signal(t)

            if is_ai and not is_non_ai:
                cur.execute(
                    "UPDATE channels SET is_ai_content = TRUE WHERE id = %s", (row_id,)
                )
                ai_true += 1
            elif is_non_ai:
                cur.execute(
                    "UPDATE channels SET is_ai_content = FALSE WHERE id = %s", (row_id,)
                )
                ai_false += 1
            else:
                skipped += 1

    logger.info(
        f"Clasificados: {ai_true} IA confirmados | "
        f"{ai_false} no-IA | "
        f"{skipped} sin señal clara (NULL — excluidos del scoring)"
    )
    logger.info("data_cleaner: done")


def _has_ai_signal(title_lower: str) -> bool:
    # También detectar título que EMPIEZA con "ai " o "ia "
    if title_lower.startswith("ai ") or title_lower.startswith("ia "):
        return True
    return any(signal in title_lower for signal in AI_SIGNALS)


def _has_non_ai_signal(title_lower: str) -> bool:
    return any(signal in title_lower for signal in NON_AI_SIGNALS)
