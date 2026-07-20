import logging
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

from redis import Redis
from rq import Worker, Queue

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    conn = Redis.from_url(os.environ["REDIS_URL"])
    queue = Queue("video_jobs", connection=conn)
    logger.info("RQ worker activo — escuchando 'video_jobs'")
    Worker([queue], connection=conn).work()
