import json
import logging
from .db import get_conn

logger = logging.getLogger(__name__)

EPSILON = 1e-6

# Mapeo título → nicho por keywords en el nombre del canal.
# Orden importa: el primero que matchea gana.
NICHE_TITLE_KEYWORDS: dict[str, list[str]] = {
    "youtube_topic_channel":  ["- topic"],                              # excluir: auto-generados YouTube Music
    "lyric_videos":           ["lyric", "letra", "letras", "lyrics"],
    "historias_historicas":   ["histor", "historian", "relatos histor", "history ia", "history ai"],
    "historias_biblicas":     ["bible", "biblia", "biblical", "bíblic", "religious"],
    "creepypasta_terror":     ["creepypasta", "terror", "miedo", "horror", "más allá"],
    "anime_ia":               ["anime"],
    "entretenimiento_animado":["circo", "cartoon", "dibujos animados", "pomni"],
    "historias_amor":         ["amor", "love story", "romance"],
    "cuentos_infantiles":     ["kids", "infantil", "niños", "fruit", "frutas", "cuento"],
    "historias_ia_generales": ["story", "stories", "historia", "relato", "generated", "ai story", "ai generated"],
}


def run():
    logger.info("niche_analyzer: start")

    _assign_missing_niches()
    _clear_old_niches()
    channels = _load_channel_metrics()
    logger.info(f"Canales IA confirmados con métricas: {len(channels)}")

    # Agrupar por nicho
    groups: dict[str, list[dict]] = {}
    for ch in channels:
        niche = ch["niche_guess"] or "sin_clasificar"
        groups.setdefault(niche, []).append(ch)

    for niche_name, ch_list in groups.items():
        if niche_name in ("sin_clasificar", "youtube_topic_channel"):
            continue
        if len(ch_list) < 2:
            continue

        demand, saturation, opportunity = _compute_scores(ch_list)
        sample = [
            {"title": c["title"], "subscribers": c["subscribers"]}
            for c in sorted(ch_list, key=lambda x: x["subscribers"], reverse=True)[:5]
        ]
        _insert_niche(niche_name, demand, saturation, opportunity, sample)
        logger.info(
            f"  {niche_name}: canales={len(ch_list)} "
            f"demand={demand:.1f} sat={saturation:.1f} opp={opportunity:.4f}"
        )

    logger.info("niche_analyzer: done")


def _clear_old_niches():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM niches")
        logger.info("Niches anteriores eliminados")


def _assign_missing_niches():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title FROM channels WHERE niche_guess IS NULL AND title IS NOT NULL"
        )
        rows = cur.fetchall()
        updated = 0
        for row_id, title in rows:
            niche = _classify_title(title)
            if niche:
                cur.execute(
                    "UPDATE channels SET niche_guess = %s WHERE id = %s",
                    (niche, row_id),
                )
                updated += 1
        logger.info(f"Canales clasificados: {updated}/{len(rows)}")


def _classify_title(title: str) -> str | None:
    t = title.lower()
    for niche, keywords in NICHE_TITLE_KEYWORDS.items():
        if any(kw in t for kw in keywords):
            return niche
    return None


def _load_channel_metrics() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT
                c.id,
                c.title,
                c.niche_guess,
                s.subscribers,
                s.total_views,
                COALESCE(AVG(v.views), 0)   AS avg_views,
                COALESCE(AVG(v.likes), 0)   AS avg_likes,
                COUNT(v.id)                  AS video_count_observed
            FROM channels c
            JOIN (
                SELECT DISTINCT ON (channel_id)
                    channel_id, subscribers, total_views
                FROM channel_snapshots
                ORDER BY channel_id, captured_at DESC
            ) s ON s.channel_id = c.id
            LEFT JOIN observed_videos v ON v.channel_id = c.id
            WHERE c.niche_guess NOT IN ('youtube_topic_channel', 'sin_clasificar')
              AND c.niche_guess IS NOT NULL
              AND c.is_ai_content = TRUE
              AND s.subscribers > 0
            GROUP BY c.id, c.title, c.niche_guess, s.subscribers, s.total_views
        """)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _compute_scores(channels: list[dict]) -> tuple[float, float, float]:
    total = len(channels)

    avg_views_per_ch = [float(c["avg_views"]) for c in channels]
    subs_per_ch = [int(c["subscribers"]) for c in channels]

    penetrations = [
        float(c["avg_views"]) / max(int(c["subscribers"]), 1)
        for c in channels
    ]

    # Canales chicos que están explotando en views — señal de formato fresco
    young_breakouts = sum(
        1 for c in channels
        if penetrations[channels.index(c)] > 2.0
        and int(c["subscribers"]) < 500_000
    )

    avg_avg_views = sum(avg_views_per_ch) / total
    avg_penetration = sum(penetrations) / total

    # Demand: 0–100
    demand = (
        min(avg_avg_views / 100_000, 10) * 5 +   # hasta 50 pts — consumo bruto
        min(avg_penetration, 10)          * 3 +   # hasta 30 pts — alcance fuera de base
        min(young_breakouts, 5)           * 4      # hasta 20 pts — breakouts recientes
    )

    # Saturation: 0–100
    dominators = sum(1 for s in subs_per_ch if s > 1_000_000)
    saturation = (dominators / total) * 80 + min(total / 5, 20)

    opportunity = demand / (saturation + EPSILON)

    return round(demand, 2), round(saturation, 2), round(opportunity, 4)


def _insert_niche(name, demand, saturation, opportunity, sample):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO niches
                (name, demand_score, saturation_score, opportunity_score, sample_channels)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (name, demand, saturation, opportunity, json.dumps(sample)),
        )
