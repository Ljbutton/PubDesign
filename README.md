<p align="center"><img src="assets/wordmark.png" alt="PubDesign" width="480"></p>

A desktop publishing app for Windows that works like Microsoft Publisher and saves real
Publisher (`.pub`) files. Make flyers, posters, newsletters, business cards, certificates,
labels and social-media graphics.

## Download

**[⬇ Download PubDesign-Setup.exe](https://github.com/Ljbutton/PubDesign/releases/latest/download/PubDesign-Setup.exe)**

Run it once. It installs PubDesign for your Windows account (no admin password needed) and
adds Start menu and desktop shortcuts. If Windows shows "Windows protected your PC", click
**More info**, then **Run anyway**. This appears because the installer isn't code-signed.

To open `.pub` files made in Microsoft Publisher, PubDesign uses free LibreOffice in the
background. If it isn't installed, PubDesign offers to install it the first time you need it.

## Updates

PubDesign checks for new versions when it starts and downloads them in the background.
When an update is ready, a yellow bar appears under the ribbon. Click **Restart now** to
install it right away. PubDesign closes, shows a small progress window and reopens by
itself. Or just keep working: the update installs automatically when you close PubDesign.
You can also check by hand under **File ▸ Info ▸ Check for Updates**.

## Features

- Office-style title bar with Save, Undo and Redo, plus a **Search** box (Alt+Q) that finds any command
- Publisher-style ribbon: **File**, **Home**, **Insert**, **Page Design** and **View**, plus
  **Shape Format**, **Text Box** and **Picture Format** tabs when something is selected
- Collapsible ribbon (Ctrl+F1) and an **Export** button for PDF, pictures and printing
- Page thumbnails, rulers, margin guides, zoom slider and Publisher's keyboard shortcuts
- Text boxes with fonts, sizes, bold/italic/underline, colors, alignment and bullets
- Publisher AutoShapes (stars, arrows, heart and more), lines and pictures
- Format Painter, page background, orientation and page sizes for print and social media
- Saves `.pub` natively; also exports PDF, PNG and JPG
- Publisher-style **Print** screen with a live preview, page ranges, paper size, two-sided and grayscale printing

## How .pub support works

Microsoft never published the `.pub` format. PubDesign's reader and writer were
reverse-engineered from real Publisher 2002–2010 files and checked against LibreOffice's
independent Publisher reader.

- `.pub` files saved by PubDesign reopen with PubDesign's own reader, with nothing lost.
- `.pub` files made in Microsoft Publisher open through LibreOffice. For complex files,
  **File ▸ Open ▸ Open a Publisher file as pictures** gives an exact, non-editable copy.

## Releasing an update (maintainer)

1. Make the changes.
2. Raise the number in `version.json` and write a one-line `notes` summary.
3. Commit and push to `main`.

GitHub Actions then builds `PubDesign.exe` on Windows, runs a self-test, packages
`PubDesign-Setup.exe` with Inno Setup and publishes it as a new Release. Every installed
copy offers the update on its next launch. Progress is under the **Actions** tab.

## Running from source (developers)

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python app.py
```

## Project layout

| File | Purpose |
| --- | --- |
| `app.py` | Main window, ribbon actions, file handling |
| `ribbon.py`, `icons.py` | Ribbon, colour and shape menus, rulers, icons |
| `canvas.py`, `autoshapes.py` | Page canvas and shape drawing |
| `pubwriter.py`, `pubreader.py` | Native `.pub` writer and reader |
| `pubblocks.py`, `escher.py`, `quill.py`, `fkp.py`, `cfb.py` | `.pub` file-format internals |
| `pub_import.py` | Opening Publisher-made files through LibreOffice |
| `updater.py`, `version.json` | Update checks and installs |
| `templates.py` | Starter designs and page sizes |
| `pubdesign.spec`, `installer.iss`, `.github/workflows/build.yml` | Windows build and installer |
| `assets/` | Logo and icon (`tools/make_logo.py` regenerates them) |
