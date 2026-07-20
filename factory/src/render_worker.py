import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from .db import get_conn

logger = logging.getLogger(__name__)

MEDIA_DIR = Path(os.environ.get("MEDIA_DIR", "/data"))
REMOTION_DIR = Path("/app/remotion")
FPS = 30


def run():
    logger.info("render_worker: start")
    for video in _load_pending_videos():
        try:
            render_video(video["id"])
        except Exception as e:
            logger.error(f"render_worker falló para video {video['id']}: {e}")
    logger.info("render_worker: done")


def render_video(video_id: int):
    video = _load_video(video_id)
    narration_duration = video["assets"].get("narration_duration_sec")
    scenes = _normalize_scenes(
        video["script"], video["niche_name"], video["assets"]["images"], narration_duration
    )

    public_assets_dir = REMOTION_DIR / "public" / "assets" / str(video_id)
    public_assets_dir.mkdir(parents=True, exist_ok=True)

    for scene in scenes:
        src_str = scene.pop("_source_path", None)
        scene["imagePath"] = _copy_into_public(src_str, public_assets_dir, video_id)

    audio_prop = None
    narration_path = video["assets"].get("narration_audio")
    if narration_path:
        audio_prop = _copy_into_public(narration_path, public_assets_dir, video_id, forced_name="narration.mp3")

    spec = {
        "scenes": scenes,
        "audioPath": audio_prop,
        "style": video["script"].get("style", {}),
    }

    spec_path = REMOTION_DIR / f"spec_{video_id}.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    renders_dir = MEDIA_DIR / "renders"
    renders_dir.mkdir(parents=True, exist_ok=True)
    out_path = renders_dir / f"{video_id}.mp4"

    logger.info(f"Renderizando video {video_id} ({len(scenes)} escenas)...")
    try:
        subprocess.run(
            [
                "npx", "remotion", "render",
                "src/index.ts",
                "MainVideo",
                str(out_path),
                f"--props={spec_path}",
                "--browser-executable=/usr/bin/chromium",
            ],
            check=True,
            cwd=str(REMOTION_DIR),
        )
    finally:
        spec_path.unlink(missing_ok=True)

    _save_render_path(video_id, str(out_path))
    logger.info(f"Video {video_id} renderizado → {out_path}")


def _copy_into_public(source: str | None, dest_dir: Path, video_id: int, forced_name: str | None = None) -> str | None:
    if not source:
        return None
    src = Path(source)
    if not src.exists():
        logger.warning(f"Asset no encontrado, se omite: {src}")
        return None
    name = forced_name or src.name
    shutil.copy(src, dest_dir / name)
    return f"assets/{video_id}/{name}"


# ─── Normalización de escenas por nicho ──────────────────────────────────────
# Python es dueño de esta lógica; Remotion solo recibe un formato uniforme.

def _normalize_scenes(
    script: dict, niche: str, image_paths: list, narration_duration_sec: float | None = None
) -> list[dict]:
    raw_scenes = script.get("scenes", [])
    normalized = []

    if niche == "lyric_videos":
        for scene, imgs in zip(raw_scenes, image_paths):
            imgs = imgs if isinstance(imgs, list) else [imgs]
            start = scene.get("start_frame", 0)
            end = scene.get("end_frame", 0)
            for sub_start, sub_end, img in _split_frame_range(start, end, imgs):
                normalized.append({
                    "text": scene.get("text", ""),
                    "startFrame": sub_start,
                    "endFrame": sub_end,
                    "animation": scene.get("animation", "fade_in"),
                    "_source_path": img,
                })
    else:
        # Claude solo estima "duration_sec" por escena; ElevenLabs no siempre
        # habla al ritmo esperado. Reescalamos proporcionalmente a la duración
        # REAL del audio para que el video no corte la narración a la mitad.
        raw_durations = [float(s.get("duration_sec", 6)) for s in raw_scenes]
        estimated_total = sum(raw_durations) or 1.0
        scale = (narration_duration_sec / estimated_total) if narration_duration_sec else 1.0

        running_frame = 0
        last_narration = ""
        for scene, imgs, raw_dur in zip(raw_scenes, image_paths, raw_durations):
            imgs = imgs if isinstance(imgs, list) else [imgs]
            duration_frames = max(int(raw_dur * scale * FPS), 1)
            # Subtítulo = lo que dice la voz en esta escena. Si viene vacío (mitad
            # de un par de imágenes que comparten narración), usar la anterior —
            # el texto debe seguir en pantalla mientras la voz sigue sonando.
            narration = scene.get("narration") or ""
            if narration:
                last_narration = narration
            caption = narration or last_narration or (scene.get("text_overlay") or "")
            for sub_start, sub_end, img in _split_frame_range(running_frame, running_frame + duration_frames, imgs):
                normalized.append({
                    "text": caption,
                    "startFrame": sub_start,
                    "endFrame": sub_end,
                    "animation": "fade_in",
                    "_source_path": img,
                })
            running_frame += duration_frames

    return normalized


def _split_frame_range(start: int, end: int, images: list) -> list[tuple[int, int, str | None]]:
    """Reparte el rango de frames de una escena entre sus imágenes (normalmente 2 —
    ver script_generator: cada escena narrativa se dobla en 2 image_prompts para
    mantener la cadencia de imagen consistente sin depender de cuántas escenas
    top-level devuelva Claude)."""
    n = max(len(images), 1)
    span = end - start
    imgs = images or [None]
    out = []
    for j, img in enumerate(imgs):
        sub_start = start + (span * j) // n
        sub_end = end if j == n - 1 else start + (span * (j + 1)) // n
        out.append((sub_start, sub_end, img))
    return out


# ─── DB helpers ──────────────────────────────────────────────────────────────

def _load_pending_videos() -> list[dict]:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM videos WHERE status = 'rendering'")
        return [{"id": row[0]} for row in cur.fetchall()]


def _load_video(video_id: int) -> dict:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT v.id, v.script, v.assets, n.name AS niche_name
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
        return {"id": row[0], "script": row[1], "assets": row[2], "niche_name": row[3]}


def _save_render_path(video_id: int, path: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE videos SET status = 'review', render_path = %s WHERE id = %s",
            (path, video_id),
        )
