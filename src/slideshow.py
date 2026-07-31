#!/usr/bin/env python3
"""Local slideshow server for exported X (Twitter) photos.

Serves a web UI and the images from a local folder (your likes or
bookmarks export by default) so a browser can display them.

Run with: python src/slideshow.py [--host HOST] [--port PORT] [--folder FOLDER]
"""

import argparse
import json
import os
import pathlib
import sys
import typing
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import main as exporter

PUBLIC_DIR = pathlib.Path(__file__).parent / "public"
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
        file_path = PUBLIC_DIR / path.lstrip("/")
        if file_path.is_file():
            self.send_file(file_path, STATIC_MIME_TYPES)
            return

        self.send_error(404, "File not found")


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
    :param folder: The default folder shown in the UI. Its images are
        allowed to be served right away; other folders become allowed
        once loaded through the UI.
    :return: The configured server, ready to serve_forever.
    """
    server = ThreadingHTTPServer((host, port), Handler)
    server.default_folder = folder
    server.allowed_roots = set()
    root = pathlib.Path(os.path.realpath(os.path.expanduser(folder)))
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
