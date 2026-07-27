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
  "token": "paste-your-x-csrf-token-here",
  "cookies": "",
  "download": false,
  "path": "."
}
```

| Key | Description |
| --- | --- |
| `token` | **Required.** The `X-Csrf-Token` value (see steps below). |
| `cookies` | **Required.** Raw `Cookie` header copied from your browser devtools (see [Cookies](#cookies)). |
| `download` | Optional. Set to `true` to also download the photos. Defaults to `false`. |
| `path` | Optional. Output directory for `data.json` and downloaded images. Defaults to the current directory. |

Then simply run:

```bash
x-liked-photos-export-x64.exe
```

A different config file can be selected with `--config path/to/config.json`. Any command line argument you pass overrides the corresponding value from the config file.

> [!NOTE]
> `config.json` contains your credentials, so it is excluded from git via `.gitignore`. Only `config.example.json` is committed.

### Command line

1. Download prebuilt binary from [here](https://github.com/jokelbaf/x-liked-photos-export/releases/latest).
2. Go to [x.com](https://x.com) and authorize.
3. Open devtools via `F12` and go to `Network` tab.
4. Copy the `X-Csrf-Token` header value from any request.
5. Go to the folder where you downloaded the binary, open terminal and run the following command:

```bash
x-liked-photos-export-x64.exe --token <token>
```

This will fetch all posts you liked and generate a **data.json** file with links to the photos.

## Downloading photos

In case you want to download the photos, add `--download` flag:

```bash
x-liked-photos-export-x64.exe --token <token> --download
```

## Cookies

The tool needs your X cookies to call the API on your behalf. To get them:

1. Go to [x.com](https://x.com) and authorize.
2. Open devtools via `F12` and go to the `Network` tab.
3. Select any request to `x.com/i/api/...`.
4. Copy the full `Cookie` request header value.

Provide it via the `cookies` key in `config.json`, or with the `--cookies` flag:

```bash
x-liked-photos-export-x64.exe --cookies <cookies> --token <token>
```

> [!NOTE]  
> Cookies must be in raw unparsed format, copied from the `Cookie` header. Similar to this:
> ```
> cookie1=value1; cookie2=value2; ...
> ```

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
