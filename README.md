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
  "mode": "likes",
  "path": ".",
  "likes_query_id": "",
  "bookmarks_query_id": ""
}
```

| Key | Description |
| --- | --- |
| `ct0` | **Required.** The `ct0` cookie. Same value as the `X-Csrf-Token` header (see [Cookies](#cookies)). |
| `auth_token` | **Required.** The `auth_token` cookie (see [Cookies](#cookies)). |
| `twid` | The `twid` cookie. Required in `likes` mode only (see [Cookies](#cookies)). |
| `download` | Optional. Set to `true` to also download the photos. Defaults to `false`. |
| `mode` | Optional. `likes` or `bookmarks`. Defaults to `likes`. |
| `path` | Optional. Output directory for `data.json` and downloaded images. Defaults to the current directory. |
| `likes_query_id` / `bookmarks_query_id` | Optional. GraphQL query ID overrides. X rotates these; copy the current ID from your browser's network tab if requests start failing with 404. |

> [!NOTE]
> `config.json` contains your credentials, so it is excluded from git via `.gitignore`. Only `config.example.json` is committed.

## Usage

```bash
python src/main.py
```

This fetches all posts you liked and generates `likes/data.json` with links to the photos.

To export your bookmarks instead:

```bash
python src/main.py --bookmarks
```

To also download the photos, add `--download`.

A different config file can be selected with `--config path/to/config.json`. Any command line argument you pass overrides the corresponding value from the config file. Run `python src/main.py --help` for the full list.

## Cookies

The tool needs two or three cookies from your browser to call the X API on your behalf. To get them:

1. Go to [x.com](https://x.com) and authorize.
2. Open devtools via `F12` and go to `Application` > `Cookies` > `https://x.com`.
3. Copy the values of:
   - `ct0` — the CSRF token. This is the same value as the `X-Csrf-Token` header you see in the `Network` tab, so you can copy it from either place.
   - `auth_token` — your login session.
   - `twid` — contains your user ID. Only needed in `likes` mode.

## Running the tests

```bash
python -m unittest discover -s tests
```
