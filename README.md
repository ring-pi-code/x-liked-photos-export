<p align="center">
  <img src="/assets/icon.ico" />
</p>

<h1 align="center">x-liked-photos-export</h1>

<p align="center">A simple tool that allows you download all your liked photos from X (Twitter).</p>

> [!NOTE]
> This is a fork of [jokelbaf/x-liked-photos-export](https://github.com/jokelbaf/x-liked-photos-export) with a working Likes endpoint fix (X rotated the GraphQL query ID) plus a few personal additions. Original author: [@jokelbaf](https://github.com/jokelbaf). See the [upstream repo](https://github.com/jokelbaf/x-liked-photos-export) for the original README and releases.

## Usage

### Config file (recommended)

Instead of passing everything on the command line, the tool reads a `config.json` file from the current directory. Copy `config.example.json` to `config.json` and fill in your values:

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

Then simply run:

```bash
x-liked-photos-export-x64.exe
```

A different config file can be selected with `--config path/to/config.json`. Any command line argument you pass overrides the corresponding value from the config file.

> [!NOTE]
> `config.json` contains your credentials, so it is excluded from git via `.gitignore`. Only `config.example.json` is committed.

### Command line

1. Download prebuilt binary from [here](https://github.com/jokelbaf/x-liked-photos-export/releases/latest).
2. Copy the `ct0`, `auth_token` and `twid` cookies from your browser (see [Cookies](#cookies)).
3. Go to the folder where you downloaded the binary, open terminal and run the following command:

```bash
x-liked-photos-export-x64.exe --ct0 <ct0> --auth-token <auth_token> --twid <twid>
```

This will fetch all posts you liked and generate a **data.json** file with links to the photos.

To export your bookmarks instead, add `--bookmarks` (`twid` is not needed there):

```bash
x-liked-photos-export-x64.exe --ct0 <ct0> --auth-token <auth_token> --bookmarks
```

## Downloading photos

In case you want to download the photos, add `--download` flag:

```bash
x-liked-photos-export-x64.exe --ct0 <ct0> --auth-token <auth_token> --twid <twid> --download
```

## Cookies

The tool needs two or three cookies from your browser to call the X API on your behalf. To get them:

1. Go to [x.com](https://x.com) and authorize.
2. Open devtools via `F12` and go to `Application` > `Cookies` > `https://x.com`.
3. Copy the values of:
   - `ct0` — the CSRF token. This is the same value as the `X-Csrf-Token` header you see in the `Network` tab, so you can copy it from either place.
   - `auth_token` — your login session.
   - `twid` — contains your user ID. Only needed in `likes` mode.

## Building from source

To build the project you are going to need python 3.12+ and poetry installed.

Run the following commands to setup the project:
```bash
git clone https://github.com/jokelbaf/x-liked-photos-export.git
cd x-liked-photos-export
poetry install
```

To build the project run:
```bash
pyinstaller --onefile --icon=assets/icon.ico src/main.py --name=x-liked-photos-export-x64
```

Your binary will be located in the `dist` folder.
