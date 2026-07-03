import os
from googleapiclient.discovery import build


def build_client():
    return build("youtube", "v3", developerKey=os.environ["YOUTUBE_API_KEY"])


def search_channels(client, keyword: str, max_results: int = 20) -> list[str]:
    """Costs ~100 quota units per call."""
    resp = (
        client.search()
        .list(q=keyword, type="channel", part="id", maxResults=max_results)
        .execute()
    )
    return [item["id"]["channelId"] for item in resp.get("items", [])]


def get_channel_details(client, channel_ids: list[str]) -> list[dict]:
    """Fetch snippet + statistics + contentDetails for up to 50 IDs. Costs 1 unit."""
    resp = (
        client.channels()
        .list(
            id=",".join(channel_ids),
            part="snippet,statistics,contentDetails",
            maxResults=50,
        )
        .execute()
    )
    return resp.get("items", [])


def get_recent_video_ids(client, uploads_playlist_id: str, max_results: int = 10) -> list[str]:
    """Get video IDs from uploads playlist. Costs 1 quota unit."""
    resp = (
        client.playlistItems()
        .list(
            playlistId=uploads_playlist_id,
            part="contentDetails",
            maxResults=max_results,
        )
        .execute()
    )
    return [item["contentDetails"]["videoId"] for item in resp.get("items", [])]


def get_video_details(client, video_ids: list[str]) -> list[dict]:
    """Fetch snippet + statistics + contentDetails for up to 50 IDs. Costs 1 unit."""
    resp = (
        client.videos()
        .list(
            id=",".join(video_ids),
            part="snippet,statistics,contentDetails",
            maxResults=50,
        )
        .execute()
    )
    return resp.get("items", [])
