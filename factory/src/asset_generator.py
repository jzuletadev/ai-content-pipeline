import base64
import json
import logging
import os
import re
import anthropic
import requests
from pathlib import Path
from elevenlabs.client import ElevenLabs
from mutagen.mp3 import MP3
from .db import get_conn

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", "/data"))
IMAGEGEN_URL = os.environ.get("IMAGEGEN_URL", "http://imagegen:7860")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
IMAGE_QC_ENABLED = os.environ.get("IMAGE_QC_ENABLED", "true").lower() == "true"
IMAGE_QC_MAX_RETRIES = int(os.environ.get("IMAGE_QC_MAX_RETRIES", "2"))

# Nichos cuyo video lleva narración TTS embebida.
# lyric_videos NO lleva TTS: el audio es la canción, se añade nativa al publicar (ver arquitectura-tecnica.md §6.4).
NICHES_WITH_NARRATION = {"historias_historicas", "historias_biblicas", "historias_ia_generales"}


def run():
    logger.info("asset_generator: start")
    for video in _load_pending_videos():
        try:
            generate_assets_for_video(video["id"])
        except Exception as e:
            logger.error(f"asset_generator falló para video {video['id']}: {e}")
    logger.info("asset_generator: done")


def generate_assets_for_video(video_id: int):
    video = _load_video(video_id)
    script = video["script"]
    niche = video["niche_name"]

    out_dir = MEDIA_DIR / "assets" / str(video_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    scenes = script.get("scenes", [])
    image_paths = _generate_images(scenes, out_dir)

    narration_path = None
    narration_duration_sec = None
    if niche in NICHES_WITH_NARRATION:
        narration_path = _generate_narration(scenes, out_dir)
        if narration_path:
            narration_duration_sec = _get_mp3_duration(narration_path)

    assets = {
        "images": image_paths,
        "narration_audio": str(narration_path) if narration_path else None,
        "narration_duration_sec": narration_duration_sec,
    }
    _save_assets(video_id, assets)
    flat = [p for scene_paths in image_paths for p in scene_paths]
    ok = sum(1 for p in flat if p)
    logger.info(f"Assets generados para video {video_id}: {ok}/{len(flat)} imágenes")


# ─── imagegen (Stable Diffusion self-hosted) — imágenes ──────────────────────

def _generate_images(scenes: list[dict], out_dir: Path) -> list[list[str | None]]:
    """Cada escena narrativa se parte en sus image_prompts (normalmente 2) —
    da variedad visual sin depender de que Claude devuelva muchas escenas
    top-level, manteniendo la cadencia de imagen predecible (ver render_worker)."""
    all_paths: list[list[str | None]] = []

    for i, scene in enumerate(scenes):
        prompts = scene.get("image_prompts") or ([scene["image_prompt"]] if scene.get("image_prompt") else [])
        scene_paths: list[str | None] = []

        for j, prompt in enumerate(prompts):
            image_path = out_dir / f"scene_{i:03d}_{j}.png"

            if image_path.exists():
                scene_paths.append(str(image_path))
                continue

            if not prompt:
                logger.warning(f"Escena {i}.{j} sin image_prompt, se omite")
                scene_paths.append(None)
                continue

            attempt = 0
            image_bytes = None
            while attempt <= IMAGE_QC_MAX_RETRIES:
                try:
                    resp = requests.post(
                        f"{IMAGEGEN_URL}/generate",
                        json={"prompt": prompt},
                        timeout=60,
                    )
                    resp.raise_for_status()
                    image_bytes = resp.content
                except Exception as e:
                    logger.error(f"imagegen falló en escena {i}.{j}: {e}")
                    break

                if not IMAGE_QC_ENABLED:
                    break

                ok, reason = _check_image_quality(image_bytes, prompt)
                if ok:
                    break
                logger.warning(f"Escena {i}.{j}: QC rechazó intento {attempt + 1} — {reason}")
                attempt += 1
            else:
                # Se agotaron los reintentos y el último intento seguía sin pasar
                # QC — mejor dejar la sub-escena sin imagen (cae a fondo negro en
                # el render) que meter una imagen rota/con texto en el video final.
                logger.warning(f"Escena {i}.{j}: se agotaron los reintentos de QC, se omite la imagen")
                image_bytes = None

            if image_bytes:
                image_path.write_bytes(image_bytes)
                scene_paths.append(str(image_path))
            else:
                scene_paths.append(None)

        all_paths.append(scene_paths)

    return all_paths


def _check_image_quality(image_bytes: bytes, prompt: str) -> tuple[bool, str]:
    """Le pide a Claude que mire la imagen generada y diga si se ve coherente
    (sin deformidades, composición legible, coincide con el prompt). Barato:
    una llamada de visión chica por imagen, vale la pena dado que el tiempo
    no es un problema (corre de noche) y filtra generaciones rotas antes del render."""
    try:
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
                    {
                        "type": "text",
                        "text": (
                            f"Esta imagen se generó con el prompt: \"{prompt}\".\n"
                            "¿Se ve coherente y utilizable como fondo de video? Rechazá si tiene "
                            "deformidades claras (cuerpos/manos rotos, elementos irreconocibles, ruido "
                            "que arruina la composición), si contiene texto/letras/palabras/carteles "
                            "legibles o intentos de texto, o si está saturada/sobrecargada de elementos "
                            "compitiendo por atención. Pequeñas imperfecciones de estilo NO cuentan "
                            "como rechazo.\n"
                            "Respondé SOLO JSON: {\"pass\": true o false, \"reason\": \"breve motivo\"}"
                        ),
                    },
                ],
            }],
        )
        text_block = next((b for b in message.content if b.type == "text"), None)
        if not text_block:
            return True, "sin respuesta de QC, se acepta por defecto"
        raw = re.sub(r"^```json\s*|\s*```$", "", text_block.text.strip())
        result = json.loads(raw)
        return bool(result.get("pass", True)), result.get("reason", "")
    except Exception as e:
        logger.warning(f"QC de imagen falló, se acepta por defecto: {e}")
        return True, "QC falló, aceptada por defecto"


# ─── ElevenLabs — narración ───────────────────────────────────────────────────

def _generate_narration(scenes: list[dict], out_dir: Path) -> Path | None:
    text_parts = [s.get("narration") or s.get("text", "") for s in scenes]
    full_text = " ".join(t for t in text_parts if t).strip()
    if not full_text:
        return None

    audio_path = out_dir / "narration.mp3"
    if audio_path.exists():
        return audio_path

    try:
        client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
        audio_stream = client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            text=full_text,
            model_id="eleven_multilingual_v2",
        )
        with open(audio_path, "wb") as f:
            for chunk in audio_stream:
                f.write(chunk)
        return audio_path
    except Exception as e:
        logger.error(f"ElevenLabs falló: {e}")
        return None


def _get_mp3_duration(path: Path) -> float | None:
    """Duración REAL del audio generado — Claude solo estima duration_sec por escena,
    y ElevenLabs no siempre habla al ritmo esperado. render_worker reescala los
    frames de las escenas a esta duración real para que el video no corte la narración."""
    try:
        return MP3(str(path)).info.length
    except Exception as e:
        logger.warning(f"No se pudo leer duración de {path}: {e}")
        return None


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _load_pending_videos() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM videos WHERE status = 'generating_assets'")
        return [{"id": row[0]} for row in cur.fetchall()]


def _load_video(video_id: int) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT v.id, v.script, n.name AS niche_name
            FROM videos v
            JOIN active_channels ac ON ac.id = v.active_channel_id
            LEFT JOIN niches n ON n.id = ac.niche_id
            WHERE v.id = %s
            """,
            (video_id,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Video {video_id} no encontrado")
        return {"id": row[0], "script": row[1], "niche_name": row[2]}


def _save_assets(video_id: int, assets: dict):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE videos SET assets = %s, status = 'rendering' WHERE id = %s",
            (json.dumps(assets), video_id),
        )
