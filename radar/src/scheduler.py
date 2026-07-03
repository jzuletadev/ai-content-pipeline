import logging
import os
from dotenv import load_dotenv

load_dotenv()  # no-op dentro de Docker; útil al correr localmente

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

from apscheduler.schedulers.blocking import BlockingScheduler
from src import channel_scraper, snapshot_writer, data_cleaner, niche_analyzer, report_builder

logger = logging.getLogger(__name__)


def run_pipeline():
    logger.info("=== Radar pipeline: start ===")
    channel_scraper.run()
    snapshot_writer.run()
    data_cleaner.run()
    niche_analyzer.run()
    report_builder.run()
    logger.info("=== Radar pipeline: done ===")


if __name__ == "__main__":
    run_pipeline()  # corre inmediatamente al arrancar

    scheduler = BlockingScheduler()
    scheduler.add_job(run_pipeline, "interval", weeks=1, id="radar_weekly")
    logger.info("Scheduler activo — próxima ejecución en 1 semana")
    scheduler.start()
