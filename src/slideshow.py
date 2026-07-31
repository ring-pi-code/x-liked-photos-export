#!/usr/bin/env python3
"""Local slideshow server for exported X (Twitter) photos.

Serves a web UI and the images from a local folder (your likes or
bookmarks export by default) so a browser can display them.

Run with: python src/slideshow.py [--host HOST] [--port PORT] [--folder FOLDER]
"""

import argparse
import datetime
import json
import os
import pathlib
import sys
import typing
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import yarl

import main as exporter

PUBLIC_DIR = (pathlib.Path(__file__).parent / "public").resolve()
"""Directory containing the web UI static files."""

IMAGE_MIME_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
    ".avif": "image/avif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
"""MIME types for the image formats the slideshow can display."""

STATIC_MIME_TYPES = {
    ".html": "text/html",
    ".js": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".ico": "image/x-icon",
    **IMAGE_MIME_TYPES,
}
"""MIME types for UI static files (plus images, e.g. a favicon)."""

DEFAULT_PORT = 8765
"""Port to listen on when --port is not given."""


class Handler(BaseHTTPRequestHandler):
    """Serves the UI, the folder listing API and (hardened) image files."""

    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        pass

    def send_json(self, data: typing.Mapping[str, typing.Any], status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def send_file(self, file_path: pathlib.Path, mime_types: typing.Mapping[str, str]) -> None:
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_types.get(file_path.suffix.lower(),
                                                        "application/octet-stream"))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        if path == "/api/config":
            self.send_json({"default_folder": self.server.default_folder})
            return

        if path == "/api/images":
            folder = query.get("folder", [""])[0].strip()
            if not folder:
                self.send_json({"error": "folder parameter is required"}, 400)
                return

            root = pathlib.Path(os.path.realpath(os.path.expanduser(folder)))
            if not root.is_dir():
                self.send_json({"error": "folder not found", "path": str(root)}, 404)
                return

            images = [
                {"name": entry.name, "path": str(entry)}
                for entry in sorted(root.iterdir())
                if entry.is_file() and entry.suffix.lower() in IMAGE_MIME_TYPES
            ]
            # Loading a folder allows its images to be served via /api/image.
            self.server.allowed_roots.add(root)
            self.send_json({"folder": str(root), "count": len(images), "images": images})
            return

        if path == "/api/posts":
            folder = query.get("folder", [""])[0].strip()
            if not folder:
                self.send_json({"error": "folder parameter is required"}, 400)
                return

            root = pathlib.Path(os.path.realpath(os.path.expanduser(folder)))
            if not root.is_dir():
                self.send_json({"error": "folder not found", "path": str(root)}, 404)
                return

            try:
                result = load_timeline_posts(
                    root,
                    sort=query.get("sort", ["desc"])[0],
                    date_from=query.get("from", [""])[0],
                    date_to=query.get("to", [""])[0],
                    offset=int(query.get("offset", ["0"])[0]),
                    limit=int(query.get("limit", ["50"])[0]),
                )
            except ValueError as e:
                self.send_json({"error": str(e)}, 400)
                return
            except exporter.ConfigError as e:
                self.send_json({"error": str(e)}, 404)
                return

            # Loading a folder allows its images to be served via /api/image.
            self.server.allowed_roots.add(root)
            self.send_json(result)
            return

        if path == "/api/image":
            file_path = query.get("path", [""])[0].strip()
            if not file_path:
                self.send_json({"error": "path parameter is required"}, 400)
                return

            file_path = pathlib.Path(os.path.realpath(os.path.expanduser(file_path)))
            if file_path.suffix.lower() not in IMAGE_MIME_TYPES:
                self.send_json({"error": "not an image file"}, 400)
                return
            if not any(file_path.is_relative_to(root) for root in self.server.allowed_roots):
                self.send_json({"error": "file is outside the loaded folders"}, 403)
                return
            if not file_path.is_file():
                self.send_json({"error": "file not found"}, 404)
                return

            self.send_file(file_path, IMAGE_MIME_TYPES)
            return

        # Static files
        if path == "/":
            path = "/index.html"
        file_path = (PUBLIC_DIR / path.lstrip("/")).resolve()
        if file_path.is_file() and file_path.is_relative_to(PUBLIC_DIR):
            self.send_file(file_path, STATIC_MIME_TYPES)
            return

        self.send_error(404, "File not found")


def parse_post_date(post: typing.Mapping[str, typing.Any]) -> datetime.datetime | None:
    """Parse a post's ISO 8601 date. Naive dates are assumed UTC.

    :param post: The post to read the date from.
    :return: The parsed date, or None if missing or unparseable.
    """
    try:
        parsed = datetime.datetime.fromisoformat(post.get("date", ""))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed


def parse_date_param(value: str, name: str) -> datetime.date:
    """Parse a YYYY-MM-DD query parameter into a date.

    :param value: The parameter value.
    :param name: The parameter name, used in the error message.
    :return: The parsed date.
    :raises ValueError: If the value is not a valid YYYY-MM-DD date.
    """
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"Invalid '{name}' date: {value!r} (expected YYYY-MM-DD)") from None


def to_media(post: typing.Mapping[str, typing.Any], root: pathlib.Path) -> typing.List[typing.Dict[str, str]]:
    """Map a post's media to timeline tiles.

    Images that were downloaded become "image" tiles pointing at the local
    file. Images that were not downloaded become "missing" placeholders,
    and each video becomes a "video" placeholder.

    :param post: The post whose media to map.
    :param root: The export folder the images were downloaded to.
    :return: The media tiles, images first, then videos.
    """
    media = []
    for url in post.get("images", []):
        name = yarl.URL(url).name
        local = root / name
        if name and local.is_file():
            media.append({"kind": "image", "name": name, "path": str(local)})
        else:
            media.append({"kind": "missing", "name": name})
    media.extend({"kind": "video"} for _ in post.get("videos", []))
    return media


def load_timeline_posts(
    root: pathlib.Path,
    *,
    sort: str = "desc",
    date_from: str = "",
    date_to: str = "",
    offset: int = 0,
    limit: int = 50,
) -> typing.Dict[str, typing.Any]:
    """Load posts from a folder's data file for the timeline page.

    Filters by date range (inclusive on both ends), sorts by date and
    paginates. Posts without a valid date sort last in both directions.

    :param root: The export folder containing data.json.
    :param sort: "desc" (newest first) or "asc" (oldest first).
    :param date_from: Only include posts on or after this YYYY-MM-DD date.
    :param date_to: Only include posts on or before this YYYY-MM-DD date.
    :param offset: How many posts to skip.
    :param limit: The page size (capped at 200).
    :return: The page of posts plus pagination info.
    :raises ValueError: If a parameter is invalid.
    :raises exporter.ConfigError: If the data file is missing or invalid.
    """
    if sort not in ("asc", "desc"):
        raise ValueError(f"Invalid 'sort': {sort!r} (expected 'asc' or 'desc')")

    start = end = None
    if date_from:
        start = datetime.datetime.combine(
            parse_date_param(date_from, "from"), datetime.time.min, datetime.timezone.utc
        )
    if date_to:
        end = datetime.datetime.combine(
            parse_date_param(date_to, "to"), datetime.time.max, datetime.timezone.utc
        )

    offset = max(0, offset)
    limit = min(max(1, limit), 200)

    posts = exporter.load_posts(root)
    dated = [(parse_post_date(post), post) for post in posts]
    if start:
        dated = [dp for dp in dated if dp[0] and dp[0] >= start]
    if end:
        dated = [dp for dp in dated if dp[0] and dp[0] <= end]

    sentinel = (datetime.datetime.min if sort == "desc" else datetime.datetime.max)
    sentinel = sentinel.replace(tzinfo=datetime.timezone.utc)
    dated.sort(key=lambda dp: dp[0] or sentinel, reverse=(sort == "desc"))

    total = len(dated)
    page = dated[offset:offset + limit]
    return {
        "folder": str(root),
        "total": total,
        "offset": offset,
        "limit": limit,
        "posts": [
            {
                "author": post.get("author", ""),
                "handle": post.get("handle", ""),
                "date": post.get("date", ""),
                "text": post.get("text", ""),
                "post_url": post.get("post_url", ""),
                "media": to_media(post, root),
            }
            for _, post in page
        ],
    }


def default_folder(config_path: pathlib.Path) -> pathlib.Path:
    """Resolve the default slideshow folder from the config file.

    Mirrors the export tool's output location: <path>/<mode>.

    :param config_path: The path to the config file, if it exists.
    :return: The default folder to show in the slideshow.
    """
    config: typing.Dict[str, typing.Any] = {}
    if config_path.is_file():
        config = exporter.load_config(config_path)
    base = pathlib.Path(config.get("path", os.curdir)).expanduser()
    return base / config.get("mode", "likes")


def make_server(host: str, port: int, folder: str) -> ThreadingHTTPServer:
    """Create the slideshow HTTP server.

    :param host: The interface to bind to.
    :param port: The port to listen on (0 picks a free one).
    :param folder: The default folder shown in the UI. Resolved to an
        absolute path. Its images are allowed to be served right away;
        other folders become allowed once loaded through the UI.
    :return: The configured server, ready to serve_forever.
    """
    folder = os.path.realpath(os.path.expanduser(folder))
    server = ThreadingHTTPServer((host, port), Handler)
    server.default_folder = folder
    server.allowed_roots = set()
    root = pathlib.Path(folder)
    if root.is_dir():
        server.allowed_roots.add(root)
    return server


def parse_args(argv: typing.Sequence[str] | None = None) -> argparse.Namespace:
    """Parse arguments.

    :param argv: The arguments to parse. Defaults to sys.argv.
    :return: The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Host a local slideshow of your exported photos in the browser."
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind to. Defaults to 127.0.0.1 (this machine only). "
             "Use 0.0.0.0 to allow other devices on your network."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to listen on. Defaults to {DEFAULT_PORT}."
    )
    parser.add_argument(
        "--folder",
        help="Image folder to start with. Defaults to <path>/<mode> from the config file "
             "(your likes or bookmarks export)."
    )
    parser.add_argument(
        "--config",
        default=exporter.DEFAULT_CONFIG_FILENAME,
        help=f"Path to a JSON config file, used to resolve the default folder. "
             f"Defaults to '{exporter.DEFAULT_CONFIG_FILENAME}' in the current directory."
    )
    return parser.parse_args(argv)


def main() -> None:
    """Entry point."""
    args = parse_args()
    folder = args.folder or str(default_folder(pathlib.Path(args.config).expanduser()))

    server = make_server(args.host, args.port, folder)
    print(f"Starting slideshow server on http://{args.host}:{args.port}")
    print(f"Default folder: {folder}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    main()
