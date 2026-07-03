import json
import logging
import os
import re
import requests
import anthropic
from .db import get_conn

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
FPS = 30

# ─── Entry point ─────────────────────────────────────────────────────────────

def run():
    logger.info("script_generator: start")
    channels = _load_active_channels()

    for ch in channels:
        pending = _load_pending_topics(ch["id"], limit=3)
        logger.info(f"Canal '{ch['name']}': {len(pending)} temas pendientes")

        for topic in pending:
            try:
                _process_topic(topic, ch)
            except Exception as e:
                logger.error(f"Error procesando topic {topic['id']}: {e}")
                _mark_topic(topic["id"], "discarded")
                _reset_scripting_video(topic["id"])

    logger.info("script_generator: done")


# ─── Procesamiento por nicho ──────────────────────────────────────────────────

def _process_topic(topic: dict, channel: dict):
    niche = channel["niche_name"]
    logger.info(f"  Procesando: {topic['title']!r} ({niche})")

    _mark_topic(topic["id"], "selected")
    video_id = _create_video(topic["id"], channel["id"])

    if niche == "lyric_videos":
        script, metadata = _generate_lyric_script(topic, channel)
    elif niche == "historias_historicas":
        script, metadata = _generate_history_script(topic, channel)
    else:
        raise ValueError(f"Sin generador para nicho: {niche}")

    _save_video_script(video_id, script, metadata)
    logger.info(f"  Video {video_id} → generating_assets")


# ─── Lyric Videos ────────────────────────────────────────────────────────────

def _generate_lyric_script(topic: dict, channel: dict) -> tuple[dict, dict]:
    parts = topic["title"].split(" — ", 1)
    song_title = parts[0].strip()
    artist = parts[1].strip() if len(parts) > 1 else "Artista"

    lyrics = _fetch_lyrics(artist, song_title)
    if not lyrics:
        raise ValueError(f"Letra no encontrada para {song_title} — {artist}")

    # Reemplazar saltos de línea con " | " para embeber en JSON sin romperlo
    lyrics = lyrics.replace("\r\n", "\n").replace("\r", "\n")
    lyrics = lyrics[:3000]
    lyrics_inline = " | ".join(line for line in lyrics.split("\n") if line.strip())

    bpm, duration_sec = _fetch_spotify_features(topic["source_ref"])

    prompt = f"""Eres el productor creativo de un canal de lyric videos en español.

Canción: {song_title}
Artista: {artist}
BPM: {bpm}
Duración: {duration_sec} segundos
FPS del video: {FPS}

Letra (separadores | indican salto de línea):
{lyrics_inline}

Generá un JSON con esta estructura exacta:
{{
  "scenes": [
    {{
      "text": "líneas de letra de esta escena (2-4 líneas)",
      "start_frame": 0,
      "end_frame": 90,
      "image_prompt": "prompt en inglés para generar imagen de fondo con Gemini (describe escena visual)",
      "animation": "fade_in"
    }}
  ],
  "style": {{
    "color_primary": "#FFFFFF",
    "color_shadow": "#000000",
    "font": "Montserrat",
    "mood": "descripción del mood visual general"
  }},
  "metadata": {{
    "title": "título para YouTube max 100 chars",
    "description": "descripción 2-3 párrafos SEO en español",
    "hashtags": ["#hashtag1", "#hashtag2"],
    "audio_ref": "{song_title} - {artist}"
  }}
}}

Reglas:
- Repartí la letra en escenas de 2-4 líneas. Calculá start_frame/end_frame según la duración total ({int(duration_sec * FPS)} frames totales).
- image_prompt debe describir una escena visual que evoque el mood de esa parte de la letra. En inglés.
- animation debe ser uno de: fade_in, slide_up, typewriter, zoom_in
- Respondé SOLO con el JSON. Sin texto adicional, sin markdown."""

    return _call_claude(prompt)


def _fetch_lyrics(artist: str, title: str) -> str | None:
    # Limpiar el título antes de buscar: quitar "(feat. ...)", "[...]", etc.
    clean_title = re.sub(r"\s*\(feat\..*?\)", "", title, flags=re.IGNORECASE)
    clean_title = re.sub(r"\s*\[.*?\]", "", clean_title)
    clean_title = clean_title.strip()

    try:
        resp = requests.get(
            f"https://api.lyrics.ovh/v1/{requests.utils.quote(artist)}/{requests.utils.quote(clean_title)}",
            timeout=10,
        )
        if resp.status_code == 200:
            lyrics = resp.json().get("lyrics", "").strip()
            if lyrics:
                return lyrics
    except Exception as e:
        logger.warning(f"lyrics.ovh falló para {artist} - {clean_title}: {e}")

    return None


def _fetch_spotify_features(source_ref: str) -> tuple[float, float]:
    # BPM y duración exactos se integran en Fase 5 (audio analysis).
    # Por ahora: defaults por género. El timing visual se ajusta con el audio real al subir.
    return 120.0, 210.0  # bpm, duration_sec


# ─── Historias Históricas ─────────────────────────────────────────────────────

def _generate_history_script(topic: dict, channel: dict) -> tuple[dict, dict]:
    prompt = f"""Eres el guionista de un canal de historias históricas narradas con IA en español.

Tema del video: {topic['title']}

Generá un JSON con esta estructura exacta:
{{
  "scenes": [
    {{
      "narration": "texto narrado de esta escena (2-4 oraciones impactantes)",
      "duration_sec": 8,
      "image_prompt": "prompt en inglés para generar imagen histórica con Gemini",
      "text_overlay": "fecha o dato clave opcional (puede ser null)"
    }}
  ],
  "voice": {{
    "style": "épico",
    "pace": "moderado"
  }},
  "metadata": {{
    "title": "título impactante para YouTube max 100 chars",
    "description": "descripción con contexto histórico SEO en español (2-3 párrafos)",
    "hashtags": ["#hashtag1", "#hashtag2"]
  }}
}}

Reglas:
- 8 a 12 escenas. Cada una ~6-10 segundos de narración.
- image_prompt debe ser detallado, estilo épico/cinematográfico, en inglés.
- Respondé SOLO con el JSON. Sin texto adicional, sin markdown."""

    return _call_claude(prompt)


# ─── Claude API ───────────────────────────────────────────────────────────────

def _call_claude(prompt: str) -> tuple[dict, dict]:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=(
            "Respondés SOLO con JSON válido y bien formado. "
            "CRÍTICO: dentro de strings JSON nunca uses saltos de línea reales — usá \\n si necesitás uno. "
            "Sin texto adicional. Sin bloques de código markdown. Sin comentarios."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    # Buscar TextBlock explícitamente — modelos con thinking devuelven ThinkingBlock primero
    text_block = next((b for b in message.content if b.type == "text"), None)
    if not text_block:
        raise ValueError("Claude no devolvió ningún TextBlock en la respuesta")

    raw = text_block.text.strip()

    # Limpiar posible markdown
    raw = re.sub(r"^```json\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    # Intentar parse directo; si falla, extraer el JSON con regex
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("No se encontró JSON válido en la respuesta de Claude")
        parsed = json.loads(match.group())

    return parsed, parsed.get("metadata", {})


# ─── DB helpers ──────────────────────────────────────────────────────────────

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


def _load_pending_topics(channel_id: int, limit: int = 3) -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, title, source_ref, trend_score
            FROM topics
            WHERE active_channel_id = %s AND status = 'pending'
            ORDER BY trend_score DESC
            LIMIT %s
            """,
            (channel_id, limit),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _mark_topic(topic_id: int, status: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE topics SET status = %s WHERE id = %s", (status, topic_id))


def _create_video(topic_id: int, channel_id: int) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO videos (topic_id, active_channel_id, status)
            VALUES (%s, %s, 'scripting')
            RETURNING id
            """,
            (topic_id, channel_id),
        )
        return cur.fetchone()[0]


def _reset_scripting_video(topic_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE videos SET status = 'queued' WHERE topic_id = %s AND status = 'scripting'",
            (topic_id,),
        )


def _save_video_script(video_id: int, script: dict, metadata: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE videos
            SET script   = %s,
                metadata = %s,
                status   = 'generating_assets'
            WHERE id = %s
            """,
            (json.dumps(script), json.dumps(metadata), video_id),
        )
