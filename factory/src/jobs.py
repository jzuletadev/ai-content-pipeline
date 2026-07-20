import logging
from .asset_generator import generate_assets_for_video
from .render_worker import render_video

logger = logging.getLogger(__name__)


def process_video(video_id: int):
    """Job de RQ: genera assets y renderiza un video completo. Cada paso es idempotente
    (salta lo ya generado), así que un retry tras fallo parcial no repite gasto de API."""
    logger.info(f"process_video({video_id}): start")
    generate_assets_for_video(video_id)
    render_video(video_id)
    logger.info(f"process_video({video_id}): done")
