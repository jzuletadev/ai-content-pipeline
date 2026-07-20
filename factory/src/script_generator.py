import json
import logging
import os
import re
import requests
import anthropic
from rq import Retry
from .db import get_conn
from .queue import get_video_queue
from .jobs import process_video

logger = logging.getLogger(__name__)

CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
FPS = 30
LYRIC_DURATION_SEC = int(os.environ.get("LYRIC_DURATION_SEC", "30"))
HISTORY_DURATION_SEC = int(os.environ.get("HISTORY_DURATION_SEC", "60"))

# Fase de pruebas: 1 solo video en curso a la vez en todo el sistema, para no
# disparar gasto de tokens (guion + QC de imágenes) en lotes. Desactivar
# (env TEST_MODE_SINGLE_VIDEO=false) cuando se valide el pipeline y se pase a
# producción real.
TEST_MODE_SINGLE_VIDEO = os.environ.get("TEST_MODE_SINGLE_VIDEO", "true").lower() == "true"

IN_PROGRESS_STATUSES = ("scripting", "generating_assets", "rendering")

# ─── Entry point ─────────────────────────────────────────────────────────────

def run():
    logger.info("script_generator: start")

    if TEST_MODE_SINGLE_VIDEO and _has_video_in_progress():
        logger.info("Ya hay un video en curso — fase de pruebas (1 a la vez), se omite esta corrida")
        return

    channels = _load_active_channels()

    for ch in channels:
        limit = 1 if TEST_MODE_SINGLE_VIDEO else 3
        pending = _load_pending_topics(ch["id"], limit=limit)
        logger.info(f"Canal '{ch['name']}': {len(pending)} temas pendientes")

        for topic in pending:
            try:
                _process_topic(topic, ch)
            except Exception as e:
                logger.error(f"Error procesando topic {topic['id']}: {e}")
                _mark_topic(topic["id"], "discarded")
                _reset_scripting_video(topic["id"])

            if TEST_MODE_SINGLE_VIDEO:
                logger.info("script_generator: done (1 video creado, fase de pruebas)")
                return

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
    get_video_queue().enqueue(
        process_video, video_id,
        job_timeout=1200,
        retry=Retry(max=2, interval=[30, 120]),
    )
    logger.info(f"  Video {video_id} → generating_assets (encolado)")


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

    total_frames = LYRIC_DURATION_SEC * FPS

    prompt = f"""Eres el productor creativo de un canal de lyric videos cortos (estilo Shorts/Reels/TikTok) en español.

Canción: {song_title}
Artista: {artist}
Formato: CORTO — duración fija de {LYRIC_DURATION_SEC} segundos ({total_frames} frames a {FPS}fps)

Letra completa (separadores | indican salto de línea):
{lyrics_inline}

Tu tarea: de toda la letra, elegí SOLO el fragmento más pegadizo y reconocible —
normalmente el estribillo/coro. NO uses la canción completa. El video final dura
exactamente {LYRIC_DURATION_SEC} segundos.

Generá un JSON con esta estructura exacta:
{{
  "scenes": [
    {{
      "text": "líneas de letra de esta escena (2-4 líneas)",
      "start_frame": 0,
      "end_frame": 90,
      "image_prompts": ["prompt A en inglés", "prompt B en inglés"],
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
    "title": "título para YouTube Shorts/TikTok max 100 chars",
    "description": "descripción corta SEO en español",
    "hashtags": ["#hashtag1", "#hashtag2", "#shorts"],
    "audio_ref": "{song_title} - {artist}"
  }}
}}

Reglas:
- El total de frames de todas las escenas DEBE sumar exactamente {total_frames} (de 0 a {total_frames}).
- 2 a 3 escenas, cada una 2-4 líneas del fragmento elegido (cada escena se
  parte en 2 imágenes al renderizar, así que pocas escenas ya dan suficiente
  variedad visual sin disparar el costo de generación/QC).
- image_prompts es SIEMPRE un array de EXACTAMENTE 2 strings en inglés — dos
  momentos o ángulos DISTINTOS dentro de esa escena (nunca la misma imagen
  repetida ni una simple variación mínima).
- Cada image_prompt DEBE empezar literalmente con "modern disney style, " —
  es el trigger word del modelo de imagen fine-tuneado que usamos (entrenado
  para ese estilo animado específico). Sin ese prefijo el modelo cae de
  nuevo en fotorrealismo. NUNCA fotorrealista ni cinematográfico.
- Composición SIMPLE y no saturada: UN sujeto/acción central claro por
  imagen, fondo simple que apoye sin competir. Nada de escenas con muchos
  elementos o personajes compitiendo por atención — es la causa más común de
  imágenes rotas.
- Descripción PRECISA y concreta (sujeto + acción + escenario específico).
  Nunca vaga, simbólica o abstracta — una descripción vaga hace que el modelo
  de imagen improvise y genere algo que no tiene relación clara con la letra.
- PROHIBIDO que la imagen incluya texto, letras, palabras, carteles o
  escritura de cualquier tipo — el modelo no puede renderizar texto legible y
  es otra fuente frecuente de errores.
- Debe evocar el mood de esa parte de la letra.
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


# ─── Historias Históricas ─────────────────────────────────────────────────────

def _generate_history_script(topic: dict, channel: dict) -> tuple[dict, dict]:
    prompt = f"""Eres el guionista de un canal de historias históricas narradas con IA en español.

Formato: CORTO — duración fija de {HISTORY_DURATION_SEC} segundos (estilo Shorts/Reels/TikTok).

Tema del video: {topic['title']}

Armá un arco narrativo completo en {HISTORY_DURATION_SEC}s: gancho (primeros ~5s) que
enganche de entrada, desarrollo con contexto y tensión, y remate/cierre con el dato
o giro más impactante. No trates de cubrir todo el tema — un ángulo concreto con
principio, desarrollo y final.

Generá un JSON con esta estructura exacta:
{{
  "scenes": [
    {{
      "narration": "texto narrado de esta escena (1-3 oraciones)",
      "duration_sec": 12,
      "image_prompts": ["prompt A en inglés", "prompt B en inglés"],
      "text_overlay": "fecha o dato clave opcional (puede ser null)"
    }}
  ],
  "voice": {{
    "style": "épico",
    "pace": "moderado"
  }},
  "metadata": {{
    "title": "título impactante para YouTube Shorts max 100 chars",
    "description": "descripción corta con contexto histórico SEO en español",
    "hashtags": ["#hashtag1", "#hashtag2", "#shorts"]
  }}
}}

Reglas:
- La suma de todos los "duration_sec" DEBE ser exactamente {HISTORY_DURATION_SEC} segundos.
- 4 a 5 escenas (~10-15s cada una: gancho, desarrollo, remate) — cada escena
  se parte en 2 imágenes al renderizar, así que pocas escenas narrativas ya
  dan suficiente variedad visual (~7-8 imágenes en total) sin disparar el
  costo de generación/QC de más escenas.
- image_prompts es SIEMPRE un array de EXACTAMENTE 2 strings en inglés — dos
  momentos o ángulos DISTINTOS dentro de esa escena (nunca la misma imagen
  repetida ni una simple variación mínima).
- Cada image_prompt DEBE empezar literalmente con "modern disney style, " —
  es el trigger word del modelo de imagen fine-tuneado que usamos (entrenado
  para ese estilo animado específico). Sin ese prefijo el modelo cae de
  nuevo en fotorrealismo. NUNCA fotorrealista ni cinematográfico.
- Composición SIMPLE y no saturada: UN sujeto/acción central claro por
  imagen, fondo simple que apoye sin competir. Nada de escenas con muchos
  elementos o personajes compitiendo por atención — es la causa más común de
  imágenes rotas.
- Descripción PRECISA y concreta (sujeto + acción + escenario específico,
  época/vestimenta si aplica). Nunca vaga, simbólica o abstracta — una
  descripción vaga hace que el modelo de imagen improvise y genere algo sin
  relación clara con la escena histórica.
- PROHIBIDO que la imagen incluya texto, letras, palabras, carteles o
  escritura de cualquier tipo — el modelo no puede renderizar texto legible y
  es otra fuente frecuente de errores.
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

def _has_video_in_progress() -> bool:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM videos WHERE status = ANY(%s) LIMIT 1",
            (list(IN_PROGRESS_STATUSES),),
        )
        return cur.fetchone() is not None


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
