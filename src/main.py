import asyncio
import argparse
import sys
import typing
import logging
import json
import yarl
import os
import pathlib
from datetime import datetime

import aiohttp
from tqdm.auto import tqdm


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s]: %(message)s")

URL_TEMPLATES: typing.Mapping[str, str] = {
    mode: f"https://x.com/i/api/graphql/{{query_id}}/{endpoint}?"
    for mode, endpoint in (("likes", "Likes"), ("bookmarks", "Bookmarks"))
}
"""The URLs to fetch data from, per mode."""

HEADERS: typing.Mapping[str, str] = {
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://x.com/",
    "Origin": "https://x.com",
    "X-Twitter-Auth-Type": "OAuth2Session",
    "X-Twitter-Active-User": "yes",
    "X-Twitter-Client-Language": "en",
}
"""Default headers appliable to all requests."""

QUERY: typing.Dict[str, typing.Dict[str, typing.Any]] = {
    "variables": {
        "count": 100,
        "includePromotedContent": False,
        "withClientEventToken": False,
        "withBirdwatchNotes":False,
        "withVoice": True,
        "withV2Timeline": True
    },
    "features": {
        "rweb_tipjar_consumption_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "articles_preview_enabled": True,
        "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "creator_subscriptions_quote_tweet_preview_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "rweb_video_timestamps_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_enhance_cards_enabled": False
    },
    "fieldToggles": {
        "withArticlePlainText": False
    }
}
"""GraphQL query to fetch liked tweets."""

MODES: typing.Mapping[str, typing.Mapping[str, typing.Any]] = {
    "likes": {
        "query": QUERY,
        "needs_user_id": True,
        "error_label": "Likes",
    },
    "bookmarks": {
        "query": {
            **QUERY,
            "variables": {
                "count": QUERY["variables"]["count"],
                "includePromotedContent": False,
            },
        },
        "needs_user_id": False,
        "error_label": "Bookmarks",
    },
}
"""Per-mode settings: GraphQL query, whether it needs a userId, and error label.

Bookmarks are always the authenticated user's, so no userId is sent."""

DEFAULT_CONFIG_FILENAME = "config.json"
"""Config filename to look for in the current directory."""

CONFIG_KEYS = {
    "ct0", "auth_token", "twid", "download", "mode", "path", "4k",
    "likes_query_id", "bookmarks_query_id",
}
"""Keys allowed in the config file."""


class ConfigError(Exception):
    """Raised when the config file is missing, malformed or invalid."""


def load_config(path: pathlib.Path) -> typing.Dict[str, typing.Any]:
    """Load settings from a JSON config file.

    :param path: The path to the config file.
    :return: The settings from the config file.
    :raises ConfigError: If the file does not exist, is not valid JSON
        or contains an invalid value.
    """
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")

    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config file {path} contains invalid JSON: {e}") from e

    if not isinstance(config, dict):
        raise ConfigError(f"Config file {path} must contain a JSON object.")

    if unknown_keys := sorted(set(config) - CONFIG_KEYS):
        logger.warning(
            f"Ignoring unknown config keys: {', '.join(unknown_keys)} "
            f"(allowed keys: {', '.join(sorted(CONFIG_KEYS))})"
        )

    for key in ("download", "4k"):
        if key in config and not isinstance(config[key], bool):
            raise ConfigError(f"Config value '{key}' must be true or false, got: {config[key]!r}")
    for key in ("ct0", "auth_token", "twid", "mode", "path", "likes_query_id", "bookmarks_query_id"):
        if key in config and config[key] is not None and not isinstance(config[key], str):
            raise ConfigError(f"Config value '{key}' must be a string, got: {config[key]!r}")
    if "mode" in config and config["mode"] not in MODES:
        raise ConfigError(f"Config value 'mode' must be one of: {', '.join(sorted(MODES))}")

    return config


def get_query(
    data: typing.Dict[str, typing.Dict[str, typing.Any]],
    *,
    user_id: str | None = None,
    cursor: str | None = None,
) -> typing.Dict[str, str]:
    """Obtain query.
    
    :param data: The data to convert to a query.
    :param user_id: The user ID to include in the variables, if needed.
    :param cursor: The pagination cursor, if any.
    :return: The query.
    """
    query: typing.Dict[str, str] = {}
    for key, value in data.items():
        if key == "variables":
            value = {
                **({"cursor": cursor} if cursor is not None else {}),
                **({"userId": user_id} if user_id else {}),
                **value,
            }
        query[key] = json.dumps(value, separators=(",", ":"))

    return query


def format_created_at(created_at: str) -> str:
    """Convert X's created_at date to ISO 8601.

    :param created_at: The date as returned by X, e.g. "Thu Jul 30 13:26:30 +0000 2026".
    :return: The date in ISO 8601, or the original value if it cannot be parsed.
    """
    try:
        return datetime.strptime(created_at, "%a %b %d %H:%M:%S %z %Y").isoformat()
    except ValueError:
        return created_at


def best_video_url(media: typing.Dict[str, typing.Any]) -> str | None:
    """Pick the highest-bitrate MP4 variant of a video media.

    :param media: The media entry from a tweet's extended_entities.
    :return: The MP4 URL, or None if the media has no video variants.
    """
    variants = (media.get("video_info") or {}).get("variants") or []
    mp4s = [v for v in variants if v.get("content_type") == "video/mp4" and v.get("url")]
    if not mp4s:
        return None
    return max(mp4s, key=lambda v: v.get("bitrate") or 0)["url"]


def parse_tweet(result: typing.Dict[str, typing.Any]) -> typing.Dict[str, typing.Any] | None:
    """Extract post details from a single tweet result.

    :param result: The tweet result from a "tweet_results" entry.
    :return: The post details, or None if the tweet has no images and no videos.
    """
    if not isinstance(result, dict):
        return None
    if result.get("__typename") == "TweetWithVisibilityResults":
        result = result.get("tweet") or {}

    legacy = result.get("legacy") or {}
    media = (legacy.get("extended_entities") or {}).get("media") or []
    images = [m["media_url_https"] for m in media
              if m.get("type") == "photo" and m.get("media_url_https")]
    videos = [url for m in media if (url := best_video_url(m))]
    if not images and not videos:
        return None

    user_result = (result.get("core") or {}).get("user_results") or {}
    user_core = (user_result.get("result") or {}).get("core") or {}
    handle = user_core.get("screen_name", "")
    rest_id = result.get("rest_id", "")

    return {
        "author": user_core.get("name", ""),
        "handle": handle,
        "date": format_created_at(legacy.get("created_at", "")),
        "text": legacy.get("full_text", ""),
        "post_url": f"https://x.com/{handle}/status/{rest_id}" if handle and rest_id else "",
        "images": images,
        "videos": videos,
    }


def parse_posts(data: typing.Dict[str, typing.Any]) -> typing.List[typing.Dict[str, typing.Any]]:
    """Extract posts with images from a GraphQL response.

    :param data: The GraphQL response data.
    :return: The posts with their details and image URLs,
        in the order they appear in the response.
    """
    posts: typing.List[typing.Dict[str, typing.Any]] = []

    def search(d: typing.Dict[str, typing.Any] | typing.Sequence[typing.Any]) -> None:
        if isinstance(d, dict):
            if "tweet_results" in d:
                post = parse_tweet((d["tweet_results"] or {}).get("result"))
                if post:
                    posts.append(post)
                return
            for value in d.values():
                search(value)
        elif isinstance(d, list):
            for item in d:
                search(item)

    search(data)
    return posts


def get_bottom_cursor(data: typing.Dict[str, typing.Any]) -> str | None:
    """Get the bottom cursor.
    
    :param data: The data to search for the bottom cursor.
    :return: The bottom cursor if found.
    """

    def search(d: typing.Dict[str, typing.Any] | typing.Sequence[typing.Any]) -> None:
        if isinstance(d, dict):
            if d.get("cursorType") == "Bottom":
                return d.get("value")
            for value in d.values():
                if result := search(value):
                    return result
        elif isinstance(d, list):
            for item in d:
                if result := search(item):
                    return result

    return search(data)


async def collect_posts(
    cookies: typing.Mapping[str, str],
    ct0: str,
    *,
    mode: str,
    query_id: str,
    cursor: str | None = None,
    progress: tqdm,  # type: ignore[reportUnknownParameterType]
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Collect posts with images.

    :param cookies: The cookies to use.
    :param ct0: The CSRF token (same value as the 'x-csrf-token' header).
    :param mode: The export mode ('likes' or 'bookmarks').
    :param query_id: The GraphQL query ID for the mode's endpoint.
    :param cursor: The pagination cursor, if any.
    :param progress: The progress bar, updated with the number of images found.
    :return: The posts with their details and image URLs.
    """
    mode_config = MODES[mode]
    twid = cookies.get("twid", "")
    user_id = twid.removeprefix("u%3D").removeprefix("u=") if mode_config["needs_user_id"] else None
    query = get_query(mode_config["query"], user_id=user_id, cursor=cursor)
    url = yarl.URL(URL_TEMPLATES[mode].format(query_id=query_id)).with_query(query)
    async with (
        aiohttp.ClientSession(
            headers={**HEADERS, "x-csrf-token": ct0},
            cookies=cookies,
        ) as session,
        session.get(url) as response
    ):
        if not response.ok:
            progress.clear()
            logger.error(f"{mode_config['error_label']} request failed with status code: {response.status}")
            sys.exit(1)

        data = await response.json()
        posts = parse_posts(data)
        media_count = sum(len(post["images"]) + len(post["videos"]) for post in posts)

        progress.update(media_count)

        if (cursor := get_bottom_cursor(data)) and media_count != 0:
            more_posts = await collect_posts(
                cookies, ct0, mode=mode, query_id=query_id, cursor=cursor, progress=progress
            )
            posts = posts + more_posts

        return posts


def dedupe_posts(
    posts: typing.List[typing.Dict[str, typing.Any]],
) -> typing.List[typing.Dict[str, typing.Any]]:
    """Remove duplicate posts, keeping the first occurrence of each.

    Posts are identified by their post URL, or by their first media URL
    when the post URL is missing.

    :param posts: The posts to deduplicate.
    :return: The deduplicated posts, in their original order.
    """
    unique: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    for post in posts:
        unique.setdefault(post["post_url"] or (post["images"] + post["videos"])[0], post)
    return list(unique.values())


def to_4k_url(url: str) -> str:
    """Rewrite an image URL to request the 4K version.

    X serves the original image when no 4K version exists, so this is
    safe to apply to any image URL.

    :param url: The image URL, e.g. "https://pbs.twimg.com/media/a.jpg".
    :return: The URL with a 4K request query, or the original URL
        if it has no extension.
    """
    parsed = yarl.URL(url)
    extension = parsed.suffix.lstrip(".")
    if not extension:
        return url
    return str(parsed.with_query({"format": extension, "name": "4096x4096"}))


def save_to_file(posts: typing.List[typing.Dict[str, typing.Any]], path: pathlib.Path) -> None:
    """Save posts to a file.

    :param posts: The posts to save.
    :param path: The path to save the data to.
    """
    with open(path / "data.json", "w") as f:
        json.dump(posts, f, indent=4)


async def download_images(posts: typing.List[typing.Dict[str, typing.Any]], path: pathlib.Path) -> None:
    """Download images.

    Images that already exist are skipped, so an interrupted run can be
    resumed by running the tool again. Each image is written to a ".part"
    file and renamed once complete, so a crash never leaves a partial
    image behind under its final name.

    :param posts: The posts whose images to download.
    :param path: The path to download the images to.
    """
    urls = [url for post in posts for url in post["images"]]
    async with aiohttp.ClientSession() as session:
        for url in tqdm(urls, desc="Downloading images", unit=""):
            target = path / yarl.URL(url).name
            if target.exists():
                continue
            partial = target.with_name(target.name + ".part")
            async with session.get(url) as response:
                data = await response.read()
                partial.write_bytes(data)
            partial.rename(target)


def parse_args(argv: typing.Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments.

    :param argv: The arguments to parse. Defaults to sys.argv.
    :return: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="A simple tool that allows you download all your liked photos from X (Twitter)."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=DEFAULT_CONFIG_FILENAME,
        help=f"Path to a JSON config file. Defaults to '{DEFAULT_CONFIG_FILENAME}' "
             "in the current directory if it exists."
    )
    parser.add_argument(
        "--ct0",
        type=str,
        help="The 'ct0' cookie. Same value as the 'x-csrf-token' header in your browser network tab."
    )
    parser.add_argument(
        "--auth-token",
        type=str,
        help="The 'auth_token' cookie from your browser."
    )
    parser.add_argument(
        "--twid",
        type=str,
        help="The 'twid' cookie from your browser. Only needed in likes mode."
    )
    parser.add_argument(
        "--download",
        action="store_true",
        default=None,
        help="Whether to download extracted images to your machine."
    )
    parser.add_argument(
        "--path",
        type=str,
        help="Location for the script output (both the data file and downloaded images)."
    )
    parser.add_argument(
        "--bookmarks",
        action="store_true",
        default=None,
        help="Export bookmarked photos instead of liked ones."
    )
    parser.add_argument(
        "--4k",
        dest="request_4k",
        action="store_true",
        default=None,
        help="Request 4K versions of images when available."
    )
    return parser.parse_args(argv)


def resolve_settings(args: argparse.Namespace) -> typing.Dict[str, typing.Any]:
    """Merge CLI arguments with the config file into effective settings.

    CLI arguments take precedence over config file values.

    :param args: The parsed CLI arguments.
    :return: The effective settings with keys: cookies, ct0, download, path,
        mode, query_id.
    """
    config_path = pathlib.Path(args.config).expanduser()
    config_exists = config_path.is_file()
    if args.config != DEFAULT_CONFIG_FILENAME and not config_exists:
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    config: typing.Dict[str, typing.Any] = {}
    if config_exists:
        try:
            config = load_config(config_path)
        except ConfigError as e:
            logger.error(str(e))
            sys.exit(1)
        logger.info(f"Loaded config from {config_path}")

    def pick(cli_value: typing.Any, key: str, default: typing.Any = None) -> typing.Any:
        return cli_value if cli_value is not None else config.get(key, default)

    bookmarks = pick(args.bookmarks, "bookmarks", None)
    mode = "bookmarks" if bookmarks else pick(None, "mode", "likes")

    download = pick(args.download, "download", False)
    request_4k = pick(args.request_4k, "4k", False)
    base_path = pathlib.Path(pick(args.path, "path", os.curdir)).expanduser()
    if not base_path.is_dir():
        logger.error(f"The output path is not a directory: {base_path}")
        sys.exit(1)
    path = base_path / mode
    path.mkdir(parents=True, exist_ok=True)

    ct0 = pick(args.ct0, "ct0")
    if not ct0:
        logger.error(
            "Missing 'ct0'. Copy the 'ct0' cookie (same value as the 'x-csrf-token' header) "
            f"from your browser into the 'ct0' key of {DEFAULT_CONFIG_FILENAME} (see README)."
        )
        sys.exit(1)

    auth_token = pick(args.auth_token, "auth_token")
    if not auth_token:
        logger.error(
            "Missing 'auth_token'. Copy the 'auth_token' cookie from your browser "
            f"into the 'auth_token' key of {DEFAULT_CONFIG_FILENAME} (see README)."
        )
        sys.exit(1)

    twid = pick(args.twid, "twid", "")
    if mode == "likes" and not twid:
        logger.error(
            "Missing 'twid'. Likes mode needs your user ID, which is taken from the 'twid' "
            f"cookie. Copy it into the 'twid' key of {DEFAULT_CONFIG_FILENAME} (see README)."
        )
        sys.exit(1)

    cookies = {"auth_token": auth_token, "ct0": ct0, **({"twid": twid} if twid else {})}

    query_id_key = f"{mode}_query_id"
    query_id = config.get(query_id_key)
    if not query_id:
        logger.error(
            f"Missing '{query_id_key}'. Copy the current {mode.capitalize()} query ID "
            f"from your browser's network tab into the '{query_id_key}' key "
            f"of {DEFAULT_CONFIG_FILENAME} (see README)."
        )
        sys.exit(1)

    return {
        "cookies": cookies,
        "ct0": ct0,
        "download": download,
        "4k": request_4k,
        "path": path,
        "mode": mode,
        "query_id": query_id,
    }


async def main() -> None:
    """Entry point."""
    args = parse_args()
    settings = resolve_settings(args)

    logger.info(f"Mode: {settings['mode']} | Output: {settings['path']}")

    progress = tqdm(desc="Fetching images", unit="")
    posts = await collect_posts(
        settings["cookies"],
        settings["ct0"],
        mode=settings["mode"],
        query_id=settings["query_id"],
        progress=progress,
    )
    progress.close()

    before = len(posts)
    posts = dedupe_posts(posts)
    if removed := before - len(posts):
        logger.info(f"Removed {removed} duplicate posts")

    if settings["4k"]:
        logger.info("Requesting 4K image versions")
        for post in posts:
            post["images"] = [to_4k_url(url) for url in post["images"]]

    save_to_file(posts, settings["path"])

    if settings["download"]:
        await download_images(posts, settings["path"])

    logger.info("Report success")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
