<p align="center">
  <img src="/assets/icon.ico" />
</p>

<h1 align="center">x-liked-photos-export</h1>

<p align="center">A simple tool that allows you download all your liked photos from X (Twitter).</p>

> [!NOTE]
> This is a fork of [jokelbaf/x-liked-photos-export](https://github.com/jokelbaf/x-liked-photos-export) with a working Likes endpoint fix (X rotated the GraphQL query ID) plus a few personal additions. Original author: [@jokelbaf](https://github.com/jokelbaf). See the [upstream repo](https://github.com/jokelbaf/x-liked-photos-export) for the original README and releases.

## Usage

> [!WARNING]  
> If you are logged in in multiple browsers with different accounts, you might get a 403 error because of cookies mismatch. In this case, you should provide the cookies manually, as shown [below](#cookies).

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

By default the tool will extract the cookies from your browser to perform requests to the API on your behalf. If you want to provide the cookies manually, you can do so by using the `--cookies` flag:

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
