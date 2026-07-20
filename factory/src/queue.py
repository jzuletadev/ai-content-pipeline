import os
from redis import Redis
from rq import Queue


def get_video_queue() -> Queue:
    conn = Redis.from_url(os.environ["REDIS_URL"])
    return Queue("video_jobs", connection=conn)
