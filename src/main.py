import asyncio
import argparse
import sys
import typing
import logging
import json
import yarl
import os
import pathlib
from http.cookies import SimpleCookie

import aiohttp
from tqdm.auto import tqdm


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] [%(levelname)s]: %(message)s")

DEFAULT_QUERY_IDS: typing.Mapping[str, str] = {
    "likes": "4X8QeWbeJ0jwGHaXSxExRw",
    "bookmarks": "6MQ4c6ZObu34HwbVAKNR8A",
}
"""Built-in GraphQL query IDs per mode. X rotates these periodically; if a
request starts failing with 404, copy the current ID from your browser's
network tab and set it via the 'query_ids' config option."""

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

CONFIG_KEYS = {"token", "cookies", "download", "mode", "path", "query_ids"}
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

    if "download" in config and not isinstance(config["download"], bool):
        raise ConfigError(f"Config value 'download' must be true or false, got: {config['download']!r}")
    for key in ("token", "cookies", "mode", "path"):
        if key in config and config[key] is not None and not isinstance(config[key], str):
            raise ConfigError(f"Config value '{key}' must be a string, got: {config[key]!r}")
    if "mode" in config and config["mode"] not in MODES:
        raise ConfigError(f"Config value 'mode' must be one of: {', '.join(sorted(MODES))}")
    if "query_ids" in config and config["query_ids"] is not None:
        query_ids = config["query_ids"]
        if not isinstance(query_ids, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in query_ids.items()
        ):
            raise ConfigError("Config value 'query_ids' must be an object with string values.")

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


def find_values_by_key(data: typing.Dict[str, typing.Any], target_key: str) -> typing.List[str]:
    """Recursively searches through a dictionary and returns an array of all values 
    associated with the specified key.

    :param data: The dictionary to search through.
    :param target_key: The key to search for.
    :return: A list of values associated with the specified key.
    """
    results: typing.Sequence[str] = []

    def search(d: typing.Dict[str, typing.Any] | typing.Sequence[typing.Any]) -> None:
        if isinstance(d, dict):
            for key, value in d.items():
                if key == target_key:
                    results.append(value)
                search(value)
        elif isinstance(d, list):
            for item in d:
                search(item)

    search(data)
    return results


def get_browser_cookies() -> typing.Mapping[str, typing.Any]:
    """Load X cookies from browsers using rookiepy.

    rookiepy is imported lazily so it is only required when cookies
    are not provided explicitly.

    :return: The browser cookies as a mapping.
    """
    try:
        import rookiepy
    except ImportError:
        logger.error(
            "The 'rookiepy' package is required to read cookies from your browsers. "
            "Install it or provide cookies via the config file / --cookies."
        )
        sys.exit(1)

    cookies = rookiepy.load()
    return {cookie["name"]: cookie["value"] for cookie in cookies if cookie["domain"] == ".x.com"}


def parse_cookies(cookies: str) -> typing.Mapping[str, typing.Any]:
    """Parse cookies from raw string to dict.
    
    :param cookies: The cookies to parse.
    :return: Parsed cookies.
    """
    cookie = SimpleCookie()
    cookie.load(cookies)
    return {k: v.value for k, v in cookie.items()}


def check_cookies(cookies: typing.Mapping[str, str]) -> typing.List[str]:
    """Check if cookies are valid.
    
    :param cookies: The cookies to check.
    :return: A list of missing cookies.
    """
    required_cookies = ["auth_token", "ct0", "twid"]
    return [cookie for cookie in required_cookies if cookie not in cookies]


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


async def collect_images_urls(
    cookies: typing.Mapping[str, str],
    token: str,
    *,
    mode: str,
    query_id: str,
    cursor: str | None = None,
    progress: tqdm,  # type: ignore[reportUnknownParameterType]
) -> typing.List[str]:
    """Collect images URLs.
    
    :param cookies: The cookies to use.
    :param token: The token to use.
    :param mode: The export mode ('likes' or 'bookmarks').
    :param query_id: The GraphQL query ID for the mode's endpoint.
    :return: The images URLs.
    """
    mode_config = MODES[mode]
    user_id = cookies["twid"][4:] if mode_config["needs_user_id"] else None
    query = get_query(mode_config["query"], user_id=user_id, cursor=cursor)
    url = yarl.URL(URL_TEMPLATES[mode].format(query_id=query_id)).with_query(query)
    async with (
        aiohttp.ClientSession(
            headers={**HEADERS, "x-csrf-token": token},
            cookies=cookies,
        ) as session,
        session.get(url) as response
    ):
        if not response.ok:
            progress.clear()
            logger.error(f"{mode_config['error_label']} request failed with status code: {response.status}")
            sys.exit(1)

        data = await response.json()
        images = find_values_by_key(data, "media_url_https")

        progress.update(len(images))

        if (cursor := get_bottom_cursor(data)) and len(images) != 0:
            more_images = await collect_images_urls(
                cookies, token, mode=mode, query_id=query_id, cursor=cursor, progress=progress
            )
            images = images + more_images

        return images


def save_to_file(images: typing.List[str], path: pathlib.Path) -> None:
    """Save images urls to a file.
    
    :param data: The data to save.
    :param path: The path to save the data to.
    """
    with open(path / "data.json", "w") as f:
        json.dump(images, f, indent=4)


async def download_images(images: typing.List[str], path: pathlib.Path) -> None:
    """Download images.
    
    :param images: The images to download.
    :param path: The path to download the images to.
    """
    async with aiohttp.ClientSession() as session:
        for image in tqdm(images, desc="Downloading images", unit=""):
            async with session.get(image) as response:
                data = await response.read()
                with open(path / pathlib.Path(image).name, "wb") as f:
                    f.write(data)


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
        "--cookies", "-c",
        type=str,
        help="Raw 'Cookie' header. If not passed, reads cookies from your browsers."
    )
    parser.add_argument(
        "--token",
        type=str,
        help="'x-csrf-token' copied from your browser network tab"
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
    return parser.parse_args(argv)


def resolve_settings(args: argparse.Namespace) -> typing.Dict[str, typing.Any]:
    """Merge CLI arguments with the config file into effective settings.

    CLI arguments take precedence over config file values.

    :param args: The parsed CLI arguments.
    :return: The effective settings with keys: cookies, token, download, path,
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

    query_id = (config.get("query_ids") or {}).get(mode) or DEFAULT_QUERY_IDS[mode]

    download = pick(args.download, "download", False)
    base_path = pathlib.Path(pick(args.path, "path", os.curdir)).expanduser()
    if not base_path.is_dir():
        logger.error(f"The output path is not a directory: {base_path}")
        sys.exit(1)
    path = base_path / mode
    path.mkdir(parents=True, exist_ok=True)

    token = pick(args.token, "token")
    if not token:
        logger.error(
            "Missing 'x-csrf-token'. Provide it via --token or the 'token' key "
            f"in {DEFAULT_CONFIG_FILENAME}."
        )
        sys.exit(1)

    raw_cookies = pick(args.cookies, "cookies")
    cookies = parse_cookies(raw_cookies) if raw_cookies else get_browser_cookies()
    if missing_cookies := check_cookies(cookies):
        logger.error(f"The following required cookies are missing: {', '.join(missing_cookies)}")
        sys.exit(1)

    return {
        "cookies": cookies,
        "token": token,
        "download": download,
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
    images = await collect_images_urls(
        settings["cookies"],
        settings["token"],
        mode=settings["mode"],
        query_id=settings["query_id"],
        progress=progress,
    )
    progress.close()

    save_to_file(images, settings["path"])

    if settings["download"]:
        await download_images(images, settings["path"])

    logger.info("Report success")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
