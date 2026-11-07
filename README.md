# Bilingual Book Maker GUI

A small desktop window around [bilingual_book_maker](https://github.com/yihong0618/bilingual_book_maker).
It builds the engine's command line from a form, shows the exact command that will run, runs it,
and shows the engine's output live.

## Start

Requires Python 3.11 or newer with tkinter.

Double-click **start.bat** (Windows) or run `./start.sh` (Linux, macOS). No console window opens.
**Settings → Shortcut** puts an icon on the desktop; after that the folder is not needed again.
From a terminal: `python -m bbm_gui` or `python -m bbm_gui path/to/book.epub`.

On the first start the button reads **Install engine**. It downloads the newest engine release,
creates a private environment for it in the app's data folder and installs the pinned packages.
**Settings → Update** installs a newer release later. Any other engine folder can be chosen in Settings.

## What it does

- Pick a book (epub, txt, srt, md, pdf), the target language, and **Bilingual** or **Translation only**.
- Presets set the provider flags; the flags in effect are chips above the command, and **+** opens the list of
  every engine flag, generated from the engine itself (with the engine's own description), so new engine
  releases show up without changes here.
- Each book and mode gets its own working folder; the finished book is copied to the chosen folder
  under a name that does not overwrite anything.
- **Stop** lets the engine save its progress; **Resume** continues. A run that hits the free-tier quota stops
  before it writes failed paragraphs, and the next **Resume** translates them again.
- A custom prompt (system + user template) is edited in the **Prompt** window.

## Data

Settings, working folders and the installed engine live in the user's application data folder
(`%LOCALAPPDATA%\bbm-gui` on Windows). The API key is passed to the engine through its environment,
never on the command line.

## Licenses

The engine is MIT licensed. Its dependencies are installed on the user's machine at the user's request;
they carry their own licenses (for example PyMuPDF and EbookLib are AGPL-3.0).
