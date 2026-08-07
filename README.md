# VYREN AI

VYREN is a voice-first personal AI operating system. It boots a set of services, listens through your microphone, speaks back with synthesized voice, and can act on tools like files, browser, camera, screen capture, and computer control. Text input and a web dashboard are also available as secondary interfaces.

This README explains what VYREN is, what this repo contains, how to run it, how it is organized, and what to do when things go wrong.

---

## Table of contents

1. [What is VYREN?](#1-what-is-vyren)
2. [Who is this for?](#2-who-is-this-for)
3. [What can it do?](#3-what-can-it-do)
4. [What do I need before running it?](#4-what-do-i-need-before-running-it)
5. [Installation](#5-installation)
6. [Configuration](#6-configuration)
7. [Running VYREN](#7-running-vyren)
8. [Using VYREN](#8-using-vyren)
9. [Project structure](#9-project-structure)
10. [Tool registry](#10-tool-registry)
11. [Voice system](#11-voice-system)
12. [Web dashboard](#12-web-dashboard)
13. [Troubleshooting](#13-troubleshooting)
14. [Current project status](#14-current-project-status)
15. [Contributing](#15-contributing)
16. [License](#16-license)

---

## 1. What is VYREN?

VYREN is built around one idea: talk to it like a system, not just a chatbot. When it runs, it boots multiple services, connects to a live model session when possible, and exposes tools that let it read files, browse the web, capture the screen, take camera snapshots, open apps, and change system settings.

The long-term design goal is an AI OS with:
- persistent memory
- tool execution
- scheduling
- computer control
- vision and browser automation
- voice conversation
- a dashboard interface

This repo contains a working prototype of many of those pieces.

---

## 2. Who is this for?

- Users who want a local AI assistant with voice, tools, and a dashboard.
- Developers who want to study or extend a modular Python AI system.
- People experimenting with Gemini Live, realtime audio, browser automation, screen capture, OCR, and desktop control.

If you just want a standard chatbot, VYREN is probably more setup than you need. If you want a system you can talk to, extend, and inspect, this is aimed at you.

---

## 3. What can it do?

VYREN is not a single feature. It is a collection of subsystems. The current working capabilities include:

- Voice conversation with Gemini Live when `GEMINI_API_KEY` is configured.
- Local offline voice fallback when Gemini is unavailable.
- Text conversation in the terminal.
- File and directory operations.
- Browser control via Playwright.
- Screen capture and OCR.
- Camera snapshot support.
- Computer control including clipboard, terminal, app launching, keyboard input, and brightness control on Windows.
- Knowledge graph, world model, memory, and scheduler tools.
- Web dashboard at `http://localhost:8420`.
- Health monitoring, heartbeat checks, audit logging, and service supervision.

Many of these are wired together through a shared tool registry and a boot-time runtime manager.

---

## 4. What do I need before running it?

- Python 3.10 or newer on Windows, macOS, or Linux.
- Git if you want to clone or manage the repo.
- A Gemini API key if you want online voice and richer tool use.
- A microphone and speakers or headphones if you want voice mode.
- `ffmpeg` and browser binaries if you want browser automation.
- Administrator rights on Windows for some computer-control features like brightness control and some app launches.

This project is Windows-aware, but the core architecture is cross-platform Python.

---

## 5. Installation

### 5.1 Clone or open the repo

If you have the repo locally already, open that folder. If you want a clean copy, clone it.

### 5.2 Create and activate a virtual environment

Use the included virtual environment if it exists. If not, create one.

Windows example using PowerShell or Command Prompt:

```bat
python -m venv .venv
.venv\Scripts\activate
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 5.3 Install dependencies

Install the base runtime dependencies first. These are the ones most likely to be needed for core operation.

```bash
pip install pyyaml psutil google-genai python-dotenv fastapi uvicorn httpx websockets sounddevice numpy pyttsx3 faster-whisper pynput Pillow mss
```

Optional extras that unlock more capabilities:

```bash
pip install opencv-python easyocr pyautogui pygetwindow pyperclip watchdog beautifulsoup4 lxml
```

If you plan to use browser automation, also install Playwright and its browser binaries:

```bash
pip install playwright
playwright install chromium
```

Some packages are large. `easyocr` and `sentence-transformers` can be slow to install. The repo is designed so optional subsystems degrade gracefully when a dependency is missing, but the matching tool will report unavailable instead of crashing the whole system.

### 5.4 Environment variables

Copy `.env.example` to `.env` and fill in the values you need.

The most important value for the full voice experience is `GEMINI_API_KEY`.

```bat
copy .env.example .env
```

Then edit `.env` and add your key.

---

## 6. Configuration

VYREN reads configuration from `config.yaml` in the repo root. That file controls model choice, voice behavior, interaction modes, server settings, local models, and monitoring.

Key sections:

- `model` — model name, temperature, max output tokens.
- `voice` — whether Gemini Live is enabled.
- `interaction` — default mode, wake word behavior, conversation timeout, interrupt behavior, startup greeting.
- `server` — host and port for the dashboard.
- `connectivity` — how often connectivity is checked and thresholds for offline/recovery behavior.
- `runtime` — health checks, checkpointing, auto start.
- `local_models` — Ollama base URL and available local models.

You usually do not need to edit this file to get started. The defaults work for basic usage. Change values only when you understand what they affect.

Memory and audit paths are also configured here. By default they use the VYREN data directory rather than hardcoded absolute paths.

---

## 7. Running VYREN

The main entry point is `main.py`.

```bash
python main.py
```

That is the normal startup command from the repo root after activating the virtual environment.

When it runs, you should see a boot sequence with phases such as:
- logging
- audit
- event bus
- memory
- knowledge graph
- world model
- scheduler
- reliability
- heartbeat
- tools
- agents
- brain
- camera
- connectivity
- voice
- server
- service
- monitoring

If voice connects successfully, VYREN will become voice-active. If voice cannot connect or no API key is present, the system may stay in text mode or fallback mode.

To stop VYREN, press `Ctrl+C`.

---

## 8. Using VYREN

### 8.1 Voice

If voice is active, VYREN listens and speaks. The default wake word behavior and conversation flow are controlled in `config.yaml` and the voice subsystem.

You can also type in the terminal while voice is active. Typed input is routed into the live voice session when possible, so voice and text share one conversation instead of splitting into two separate histories.

### 8.2 Terminal commands

In the text interface, these commands are recognized:

- `/quit` — shut down VYREN.
- `/help` — show available text commands.
- `/kill` — activate the kill switch.
- `/unkill` — deactivate the kill switch.
- `/tools` — list loaded tools.
- `/memory` — show memory entries.
- `/status` — show health and connectivity status.
- `/voice` — show voice status.
- `/clear` — clear the current conversation.
- `/notices` — show pending notices.
- `/agents` — show agent status.
- `/connectivity` — show network status.

### 8.3 Web dashboard

When the server phase starts, VYREN exposes a dashboard. By default it is at:

```
http://localhost:8420
```

You can use that interface if the browser UI or dashboard code is active in your checkout.

---

## 9. Project structure

This repo is modular. The most important directories and files are:

- `main.py` — startup script. Loads `.env`, creates `RuntimeManager`, and starts the system.
- `runtime/` — runtime lifecycle, boot phases, terminal REPL, service registry.
- `boot/` — boot manager and phase definitions.
- `config.py` and `config.yaml` — configuration loading and defaults.
- `event_bus.py` — internal event system connecting subsystems.
- `memory.py`, `memory_v2.py` — memory layers.
- `knowledge_graph.py` — graph-based memory.
- `world_model.py` — model of the user's world and context.
- `scheduler.py` — scheduled jobs.
- `reliability.py`, `heartbeat.py` — health monitoring and circuit breakers.
- `heartbeat.py` — heartbeat checks and notice system.
- `brain/` — planner, reasoning, and cognition pipeline.
- `agents/` — specialized agents and coordinator.
- `tools/` — tool registry and all built-in tools.
- `computer/` — clipboard, terminal, app launching, keyboard control.
- `filesystem/` — enhanced filesystem operations.
- `browser/` — browser automation.
- `vision/` — vision module.
- `camera/` — camera capture.
- `hand_tracking/` — hand tracking.
- `voice/` — voice runtime, offline loop, and live session setup.
- `voice_engine/` — Gemini Live voice engine, protocol, diagnostics.
- `server.py`, `service.py` — web server and service management.
- `provider.py` — model provider abstraction.
- `system_prompt.py` — system prompt construction.
- `tests/` — tests and proof artifacts.
- `evidence/` — generated proof artifacts such as snapshots, OCR results, research documents, and verification JSON.

There are also several markdown files in the root that document architecture, changelogs, fixes, and review notes. Those are useful if you want to understand how the system evolved.

---

## 10. Tool registry

Tools are defined in `tools/` and registered in `tools/__init__.py`. Each tool has:
- a name
- a description
- typed parameters
- a handler function
- a safety level, either `safe` or `consequential`

The registry converts tool definitions into the format the model expects. It also executes tools, tags results with `SUCCESS`, `FAILED`, or `PARTIAL`, and enforces confirmation for consequential tools.

Current tool categories include:
- memory
- filesystem and file editing
- web and browser control
- screen capture and OCR
- vision analysis
- computer control
- scheduler and world tools
- knowledge graph tools
- system tools

You add a new capability by creating a tool module and registering it. You do not need to edit `main.py` to add tools.

---

## 11. Voice system

Voice is the primary interface. The voice path has two modes:

- Online mode using Gemini Live with realtime audio.
- Offline fallback using local TTS and Whisper-based STT when Gemini is unavailable.

The voice engine manages:
- microphone streaming
- speaker playback
- barge-in behavior
- reconnection
- tool calls during voice sessions
- turn completion and state transitions

Important files:
- `voice/runtime.py` — voice runtime, live config, system prompt, and tool subset.
- `voice_engine/engine.py` — core Gemini Live engine, workers, reconnect loop, mic callback.
- `voice_engine/protocol.py` — config dataclasses, state machine, and engine defaults.
- `voice/offline_loop.py` — local fallback conversation loop.

If voice feels quiet, cracked, or unresponsive, see the troubleshooting section. The most common causes are missing dependencies, default input device misconfiguration, or absent API keys.

---

## 12. Web dashboard

The web server exposes VYREN on a local port. The default port is `8420`.

The dashboard can provide:
- status overview
- chat or terminal-like interface
- system information
- connection to the same backend brain and tool system used by voice and text

If the port is already in use, the server may fail to bind. In that case, stop the other process using the port or change the port in `config.yaml`.

---

## 13. Troubleshooting

### No voice output or VYREN says it is quiet

- Check whether `GEMINI_API_KEY` is set in `.env`.
- Check whether `sounddevice` is installed.
- Check whether your default microphone is a real input device and not a loopback or stereo mix device.
- Use `/voice` in the text interface to inspect voice status.

### Voice sounds cracked or drops out

- Use headphones to reduce speaker bleed into the microphone.
- Close other apps that may be using the microphone.
- Check whether another app is holding exclusive control of the audio device.

### Tools not available in voice mode

- The voice session uses a curated subset of tools by default.
- If a tool is missing from voice, it may be intentionally excluded to keep the live session small and low-latency.
- Typed text mode usually has access to the full tool set.

### Browser tools fail

- Make sure Playwright is installed.
- Run `playwright install chromium`.
- Some websites bot-detect automation. If a browser tool opens a challenge page, try a different site or action.

### Camera or screen tools fail

- Camera tools depend on OS camera access and installed backends.
- Screen capture and OCR depend on optional packages. If they are missing, the tool reports unavailable instead of crashing VYREN.

### Port already in use

- The dashboard uses port `8420` by default.
- Change the port in `config.yaml` under `server.port`.
- Or stop the process using the existing port.

### Permission errors on Windows

- Some computer-control features need administrator rights.
- Run the terminal or editor as administrator if brightness control or certain app launches fail.

---

## 14. Current project status

This repo is actively developed. Major subsystems are present, but some areas are still evolving. As of the latest work, the project includes:
- working voice runtime with live config and expanded tool subset
- browser automation
- screen capture, OCR, and vision analysis
- camera and hand tracking support
- computer control for apps and brightness on Windows
- web dashboard and server
- memory, scheduler, knowledge graph, world model, and audit logging
- 50 registered tools

Known limitations remain in voice audio quality, real barge-in behavior under some hardware conditions, and browser reliability against anti-bot pages. Those are active areas of work.

Evidence artifacts for recent verification are stored in `evidence/`.

---

## 15. Contributing

This project is not currently set up as a public open-source contribution repo with formal contribution guidelines. If you want to extend it, the recommended workflow is:

1. Read `ARCHITECTURE.md` and `ARCHITECTURE_REVIEW.md`.
2. Read `AGENT.md` if it exists in your checkout.
3. Make small, targeted changes.
4. Prefer adding tools through `tools/` instead of editing core runtime paths.
5. Do not add new environment variables for non-secret settings; use `config.yaml` instead.
6. Verify changes with actual runs, not just unit tests.
7. Keep voice pipeline behavior stable when changing unrelated systems.

---

## 16. License

No license file is present in this repo snapshot. If you intend to distribute or publish this project, add a `LICENSE` file and choose the terms you want to apply.

---

## Quick-start summary

```bash
# 1. Open the repo folder
cd C:\Users\Lenovo\my-project

# 2. Activate virtual environment
.venv\Scripts\activate

# 3. Install dependencies
pip install pyyaml psutil google-genai python-dotenv fastapi uvicorn httpx websockets sounddevice numpy pyttsx3 faster-whisper pynput Pillow mss
pip install playwright
playwright install chromium

# 4. Optional extras
pip install opencv-python easyocr pyautogui pygetwindow pyperclip watchdog beautifulsoup4 lxml

# 5. Configure environment
copy .env.example .env
# edit .env and add GEMINI_API_KEY if you want online voice

# 6. Run VYREN
python main.py
```

After startup, use voice or typed text. Use `/help` in the text interface to see available commands. Open `http://localhost:8420` for the dashboard if the server is active.
