<h1 align="center">x-liked-photos-export</h1>

<p align="center">A simple tool that allows you download all your liked or bookmarked photos from X (Twitter).</p>

> [!NOTE]
> This is a fork of [jokelbaf/x-liked-photos-export](https://github.com/jokelbaf/x-liked-photos-export) with a working Likes endpoint fix (X rotated the GraphQL query ID) plus a few personal additions. Original author: [@jokelbaf](https://github.com/jokelbaf). See the [upstream repo](https://github.com/jokelbaf/x-liked-photos-export) for the original README and releases.

## Setup

You need Python 3.12 or newer installed. Then:

```bash
git clone https://github.com/ring-pi-code/x-liked-photos-export.git
cd x-liked-photos-export
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy `config.example.json` to `config.json` and fill in your values:

```json
{
  "ct0": "paste-ct0-cookie-here",
  "auth_token": "paste-auth_token-cookie-here",
  "twid": "",
  "download": false,
  "4k": false,
  "concurrency": 4,
  "mode": "likes",
  "path": ".",
  "likes_query_id": "paste-likes-query-id-here",
  "bookmarks_query_id": "paste-bookmarks-query-id-here"
}
```

| Key | Description |
| --- | --- |
| `ct0` | **Required.** The `ct0` cookie. Same value as the `X-Csrf-Token` header (see [Cookies](#cookies)). |
| `auth_token` | **Required.** The `auth_token` cookie (see [Cookies](#cookies)). |
| `twid` | The `twid` cookie. Required in `likes` mode only (see [Cookies](#cookies)). |
| `download` | Optional. Set to `true` to also download the photos. Defaults to `false`. |
| `4k` | Optional. Set to `true` to request the 4K version of each image. X serves the original when no 4K version exists. Defaults to `false`. |
| `concurrency` | Optional. How many images to download in parallel. One of `1`, `2`, `4`, `8`. Defaults to `4`. |
| `mode` | Optional. `likes` or `bookmarks`. Defaults to `likes`. |
| `path` | Optional. Output directory for `data.json` and downloaded images. Defaults to the current directory. |
| `likes_query_id` / `bookmarks_query_id` | **Required.** The GraphQL query IDs for the Likes and Bookmarks endpoints (see [Query IDs](#query-ids)). |

> [!NOTE]
> `config.json` contains your credentials, so it is excluded from git via `.gitignore`. Only `config.example.json` is committed.

## Usage

```bash
python src/main.py
```

This fetches all posts you liked and generates `likes/data.json`. Each entry holds one post's details along with its photo links:

```json
[
    {
        "author": "Jane Doe",
        "handle": "janedoe",
        "date": "2026-07-30T13:26:30+00:00",
        "text": "Post text here",
        "post_url": "https://x.com/janedoe/status/2082820130049065448",
        "images": [
            "https://pbs.twimg.com/media/HOep3W1a8AAXHjm.jpg"
        ],
        "videos": []
    }
]
```

Video posts list the highest-quality MP4 under `videos` (GIFs count as videos). Video thumbnails are not included in `images`, and videos are not downloaded.

To export your bookmarks instead:

```bash
python src/main.py --bookmarks
```

To also download the photos, add `--download`. To request 4K versions of the images, add `--4k`.

Downloads can be resumed. Images that already exist are skipped, so if a run is interrupted, run the tool again to continue where it left off. Interrupted downloads leave hidden `.part` files behind (e.g. `.photo.jpg.part`) and are retried on the next run.

> [!NOTE]
> Filenames are the same in 4K and normal mode. If you download without 4K and later enable it, already downloaded images are not replaced. Use a fresh output directory when switching.

A different config file can be selected with `--config path/to/config.json`. Any command line argument you pass overrides the corresponding value from the config file. Run `python src/main.py --help` for the full list.

## Cookies

The tool needs two or three cookies from your browser to call the X API on your behalf. To get them:

1. Go to [x.com](https://x.com) and authorize.
2. Open devtools via `F12` and go to `Application` > `Cookies` > `https://x.com`.
3. Copy the values of:
   - `ct0` — the CSRF token. This is the same value as the `X-Csrf-Token` header you see in the `Network` tab, so you can copy it from either place.
   - `auth_token` — your login session.
   - `twid` — contains your user ID. Only needed in `likes` mode.

## Query IDs

X calls its API through GraphQL, and each operation has its own query ID in the request URL. X rotates these IDs every few months, so the tool reads them from `config.json` instead of hardcoding them. To find the current IDs:

1. Go to [x.com](https://x.com) and authorize.
2. Open devtools via `F12` and go to the `Network` tab.
3. Open your [likes page](https://x.com/i/likes) in the browser tab.
4. Type `Likes` in the network filter box. You are looking for a request URL like:
   ```
   https://x.com/i/api/graphql/4X8QeWbeJ0jwGHaXSxExRw/Likes?variables=...
   ```
5. Copy the ID between `/graphql/` and `/Likes` into `likes_query_id`.
6. Repeat on your [bookmarks page](https://x.com/i/bookmarks), filtering for `Bookmarks`, and copy that ID into `bookmarks_query_id`.

If a request suddenly starts failing with 404, X has rotated the ID. Repeat the steps above and update `config.json`.

## Running the tests

```bash
python -m unittest discover -s tests
```
