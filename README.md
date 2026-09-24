# Jarvis Assistant

A voice-driven desktop assistant for Windows. It listens, sees your screen and
webcam, speaks back in a British voice, and can use your mouse and keyboard
when you let it — all through an animated on-screen face.

Its "brain" is Claude Code (via the Claude Agent SDK), so it reasons and
answers using your own Claude plan — no API key, no extra cost.

## Features

- **Talk to it** — push-to-talk or type, it replies out loud
- **Sees** — your screen, or your webcam
- **Acts** — clicks, types, opens apps (only when you allow it, with a mouse-corner emergency stop)
- **Remembers** — a simple markdown notes vault it reads and writes itself
- **Four faces** — Circuit Board, Radial, Face in the Code, Neural Core

## Capabilities

Built-in tools the assistant can call on:

- `look_at_screen` / `read_screen_text` — see the screen, or read the words on it with their positions
- `look_through_camera` — take and look at a webcam picture
- `click_text` / `click_at` — click a button or link by its on-screen label, or by exact coordinates
- `type_text` — paste text into whatever has focus
- `press_keys` — send key combinations (e.g. `ctrl+s`, `alt+tab`)
- `scroll` — scroll the window under the mouse
- `open_app` / `open_url` — launch a program or open a web address
- `list_windows` / `focus_window` — see what's open and bring a window to the front

Learned skills (taught in conversation, stored in its notes vault):

- **Multi search** — given a term, searches it across multiple engines (Google,
  DuckDuckGo, Bing, Yahoo, Reddit), takes the top results from each, and
  compiles them into a short summary — naming the standout source when
  there is one.

## Requirements

- Windows 10 or 11, 64-bit
- A Claude plan (Pro, Max, Team, or Enterprise) to sign in with

## Getting started

1. Clone or download this repo.
2. Run `Start-Jarvis-Assistant.bat`. Jarvis's window opens on its own.
3. First run only: it downloads its speech model (~1 GB), then opens a
   Claude sign-in page in your browser — authorize it to connect to your
   Claude plan.
4. Allow microphone/camera access when prompted.

Full instructions, button-by-button, are in [`READ-ME-FIRST.txt`](READ-ME-FIRST.txt).

## Project layout

| Path | What it is |
|---|---|
| `app/` | Source code — speech, vision, tool-calling, the server |
| `app/face/` | The animated face UI |
| `app/dock/` | The on-screen button dock |
| `app/jarvis.json` | Settings — name, voice, what it calls you |
| `memory/` | Where a running Jarvis keeps its notes (not included here — it's personal to each user) |

Not included in this repo: the Python virtual environment, the downloaded
speech model, and runtime logs — these are created automatically on first run.

## Credits

- **Face** — [ai-visualizer](https://github.com/jaredrhod/ai-visualizer) by Jared Rhodenizer, AGPL-3.0
- **Memory layout** — adapted from ai-memory-vault by Jared Rhodenizer, CC BY-SA 4.0
- **Brain** — [Claude Code](https://claude.com/claude-code) via the Claude Agent SDK (Anthropic)
- **Ears** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT)
- **Voice** — edge-tts (Microsoft neural voices)

Licenses for third-party components are in [`LICENSES/`](LICENSES/).
