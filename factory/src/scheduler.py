import logging
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

from apscheduler.schedulers.blocking import BlockingScheduler
from src import topic_scraper, script_generator, result_tracker

logger = logging.getLogger(__name__)


def run_pipeline():
    logger.info("=== Factory pipeline: start ===")
    topic_scraper.run()
    script_generator.run()
    result_tracker.run()
    logger.info("=== Factory pipeline: done ===")


if __name__ == "__main__":
    run_pipeline()  # ejecutar inmediatamente al arrancar

    scheduler = BlockingScheduler()
    scheduler.add_job(run_pipeline, "cron", hour=0, minute=0, id="factory_daily")
    logger.info("Scheduler activo — próxima ejecución: mañana 00:00")
    scheduler.start()
