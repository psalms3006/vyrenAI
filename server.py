"""
server.py — VYREN Web Server (FastAPI + WebSocket).

Serves the mobile-first PWA dashboard and provides:
  - REST API for system stats, memory, tools, audit log
  - WebSocket for real-time chat with streaming, tool calls, and confirmations
  - PWA manifest and service worker for iPhone home screen install

Run:  python server.py
Open:  http://localhost:8420

For iPhone access from outside your network:
  Option A (quick): ngrok http 8420
  Option B (permanent): Cloudflare Tunnel
  Option C (cloud): Deploy to Railway/Render with a VPS
"""

import asyncio
import json
import os
import platform
import sys
import time
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import safety
from memory import MemoryStore
from audit import AuditLog
from heartbeat import Heartbeat, NoticeStore
from provider import run_turn, _ollama_available, TurnResult
from system_prompt import build_system_prompt
from tools import create_registry

# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

from platform_paths import get_disk_root, get_notices_path

config.load()
memory = MemoryStore(config.get("memory.path"))
audit = AuditLog(config.get("audit.path"))
registry = create_registry(memory_store=memory)
gemini_tools = registry.to_gemini_tools()
system_prompt = build_system_prompt(memory.build_context())

# Heartbeat
notices = NoticeStore(get_notices_path())
heartbeat = Heartbeat(
    notice_store=notices,
    config=config.get("heartbeat", {
        "enabled": False, "interval_seconds": 300, "checks": []
    }),
    on_notice=lambda n: audit.info(f"Heartbeat notice: {n['message']}"),
)
if config.get("heartbeat.enabled", False):
    heartbeat.start()

app = FastAPI(title="VYREN")

# CORS — allow iPhone and any remote device to connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files directory
WEB_DIR = Path(__file__).parent / "web"

# ---------------------------------------------------------------------------
# PWA + Static Files
# ---------------------------------------------------------------------------

@app.get("/")
async def dashboard():
    """Serve the PWA dashboard."""
    return HTMLResponse(
        (WEB_DIR / "index.html").read_text(encoding="utf-8")
    )


@app.get("/manifest.json")
async def manifest():
    """PWA manifest for iPhone home screen."""
    return FileResponse(WEB_DIR / "manifest.json", media_type="application/json")


@app.get("/sw.js")
async def service_worker():
    """Service worker for offline caching."""
    return FileResponse(
        WEB_DIR / "sw.js", media_type="application/javascript"
    )


# ---------------------------------------------------------------------------
# REST API
# ---------------------------------------------------------------------------

@app.get("/api/system")
async def system_stats():
    """Real-time system information. Works on Windows, Linux, macOS."""
    mem = psutil.virtual_memory()
    disk_root = get_disk_root()
    try:
        disk = psutil.disk_usage(disk_root)
        disk_data = {
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 1),
            "disk_total_gb": round(disk.total / (1024**3), 1),
        }
    except Exception:
        disk_data = {"disk_percent": 0, "disk_free_gb": 0, "disk_total_gb": 0}

    battery = psutil.sensors_battery()
    try:
        boot_time = psutil.boot_time()
        uptime = int(time.time() - boot_time)
    except Exception:
        uptime = 0

    return {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "cpu_cores": psutil.cpu_count(logical=True),
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 1),
        "memory_total_gb": round(mem.total / (1024**3), 1),
        "disk_percent": disk_data["disk_percent"],
        "disk_free_gb": disk_data["disk_free_gb"],
        "disk_total_gb": disk_data["disk_total_gb"],
        "battery_percent": battery.percent if battery else None,
        "battery_charging": battery.power_plugged if battery else None,
        "uptime_seconds": uptime,
        "hostname": platform.node(),
        "os": f"{platform.system()} {platform.release()}",
        "tool_count": len(registry.tool_names()),
        "memory_entries": memory.count(),
        "ollama_available": _ollama_available(),
    }


@app.get("/api/memory")
async def get_memory():
    """All stored memory entries."""
    return memory.list_all()


@app.get("/api/tools")
async def get_tools():
    """List all registered tools with their safety level."""
    return [
        {
            "name": t.name,
            "description": t.description[:100],
            "safety_level": t.safety_level,
        }
        for t in registry.all_tools()
    ]


@app.get("/api/audit")
async def get_audit(limit: int = 50):
    """Recent audit log entries."""
    try:
        with open(audit.path, "r") as f:
            lines = f.readlines()
        recent = [l.strip() for l in lines[-limit:] if l.strip()]
        return {"entries": recent}
    except Exception:
        return {"entries": []}


@app.get("/api/notices")
async def get_notices():
    """Pending proactive notices from the heartbeat."""
    return {"pending": notices.get_pending()}


@app.post("/api/notices/{notice_id}/dismiss")
async def dismiss_notice(notice_id: str):
    """Dismiss a proactive notice."""
    success = notices.dismiss(notice_id)
    return {"dismissed": success}


@app.get("/api/heartbeat")
async def heartbeat_status():
    """Heartbeat status."""
    return heartbeat.get_status()


# ---------------------------------------------------------------------------
# WebSocket Chat
# ---------------------------------------------------------------------------

@app.websocket("/ws/chat")
async def chat(websocket: WebSocket):
    await websocket.accept()
    history: list[dict] = []
    audit.info("WebSocket client connected")

    try:
        while True:
            # Wait for user message
            data = json.loads(await websocket.receive_text())

            # Handle slash commands
            if data.get("type") == "message":
                text = data["text"].strip().lower()
                if text == "/kill":
                    safety.activate_kill_switch()
                    await websocket.send_json({
                        "type": "system_msg",
                        "system_msg": "Kill switch activated.",
                    })
                    audit.security("Kill switch activated (web)")
                    continue
                elif text == "/unkill":
                    safety.deactivate_kill_switch()
                    await websocket.send_json({
                        "type": "system_msg",
                        "system_msg": "Kill switch deactivated.",
                    })
                    audit.security("Kill switch deactivated (web)")
                    continue
                elif text == "/tools":
                    tools_info = "\n".join(
                        f"  {t.name} [{t.safety_level}] — {t.description[:60]}"
                        for t in registry.all_tools()
                    )
                    await websocket.send_json({
                        "type": "system_msg",
                        "system_msg": f"Tools ({len(registry.tool_names())}):\n{tools_info}",
                    })
                    continue
                elif text == "/memory":
                    facts = memory.list_all()
                    if not facts:
                        mem_text = "Memory is empty."
                    else:
                        mem_text = "\n".join(
                            f"  {f['key']}: {f['value']}" for f in facts
                        )
                    await websocket.send_json({
                        "type": "system_msg",
                        "system_msg": f"Memory ({len(facts)}):\n{mem_text}",
                    })
                    continue
                elif text == "/clear":
                    history.clear()
                    await websocket.send_json({
                        "type": "system_msg",
                        "system_msg": "Conversation cleared.",
                    })
                    audit.info("Web conversation cleared")
                    continue

            if data.get("type") != "message":
                continue

            user_text = data["text"].strip()
            if not user_text:
                continue

            history.append({"role": "user", "parts": [{"text": user_text}]})
            audit.model_turn("user", user_text)

            # Stream chunks via queue
            chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
            loop = asyncio.get_event_loop()

            def make_on_chunk(q: asyncio.Queue) -> callable:
                """Create a fresh on_chunk callback bound to a specific queue."""
                def on_chunk(text: str):
                    try:
                        q.put_nowait(text)
                    except asyncio.QueueFull:
                        pass
                return on_chunk

            async def stream_chunks(q: asyncio.Queue):
                try:
                    while True:
                        chunk = await asyncio.wait_for(
                            q.get(), timeout=2.0
                        )
                        if chunk is None:
                            break
                        await websocket.send_json(
                            {"type": "chunk", "text": chunk}
                        )
                except asyncio.TimeoutError:
                    pass

            # Run model turn (blocking) in thread pool
            on_chunk = make_on_chunk(chunk_queue)
            sender = asyncio.create_task(stream_chunks(chunk_queue))
            try:
                result = await loop.run_in_executor(
                    None, run_turn, history, system_prompt, gemini_tools, on_chunk
                )
            finally:
                chunk_queue.put_nowait(None)
                await asyncio.sleep(0.1)
                sender.cancel()

            # Tool-calling loop
            max_rounds = 10
            for _ in range(max_rounds):
                if not result.function_calls:
                    break

                # Add model response to history
                model_parts = []
                if result.text:
                    model_parts.append({"text": result.text})
                for fc in result.function_calls:
                    model_parts.append({
                        "function_call": {"name": fc.name, "args": fc.args}
                    })
                history.append({"role": "model", "parts": model_parts})

                # Check for consequential tools — ask confirmation
                confirmations: dict[str, bool] = {}
                for fc in result.function_calls:
                    if registry.is_consequential(fc.name):
                        await websocket.send_json({
                            "type": "confirmation_required",
                            "name": fc.name,
                            "args": fc.args,
                        })
                        # Wait for user's response
                        try:
                            resp = json.loads(await asyncio.wait_for(
                                websocket.receive_text(), timeout=120
                            ))
                            approved = resp.get("approved", False)
                        except asyncio.TimeoutError:
                            approved = False
                        confirmations[fc.name] = approved
                        audit.confirmation(fc.name, fc.args, approved)

                # Execute tools
                tool_results = []
                for fc in result.function_calls:
                    await websocket.send_json({
                        "type": "tool_call",
                        "name": fc.name,
                        "args": fc.args,
                    })

                    if fc.name in confirmations and not confirmations[fc.name]:
                        await websocket.send_json({
                            "type": "tool_declined",
                            "name": fc.name,
                        })
                        tool_results.append({
                            "function_response": {
                                "name": fc.name,
                                "response": {
                                    "result": "User declined this action. "
                                    "Do not retry without asking again."
                                },
                            }
                        })
                        continue

                    # Handle sentinel values (post-confirmation execution)
                    audit.info(f"Executing tool: {fc.name}")
                    tool_output = registry.execute(fc.name, fc.args)
                    audit.tool_call(fc.name, fc.args, tool_output[:100])

                    if tool_output.endswith("_REQUESTED"):
                        tool_output = _execute_post_confirmation(
                            fc.name, fc.args, tool_output
                        )

                    await websocket.send_json({
                        "type": "tool_result",
                        "name": fc.name,
                        "result": tool_output[:300],
                    })

                    tool_results.append({
                        "function_response": {
                            "name": fc.name,
                            "response": {"result": tool_output},
                        }
                    })

                history.append({"role": "user", "parts": tool_results})

                # Next model turn — fresh queue and on_chunk each round
                next_queue: asyncio.Queue[str | None] = asyncio.Queue()
                next_on_chunk = make_on_chunk(next_queue)
                sender = asyncio.create_task(stream_chunks(next_queue))
                try:
                    result = await loop.run_in_executor(
                        None, run_turn, history, system_prompt, gemini_tools, next_on_chunk
                    )
                finally:
                    next_queue.put_nowait(None)
                    await asyncio.sleep(0.1)
                    sender.cancel()

            # Done
            if result.text:
                history.append({"role": "model", "parts": [{"text": result.text}]})
                audit.model_turn("model", result.text)

            await websocket.send_json({"type": "done"})

    except WebSocketDisconnect:
        audit.info("WebSocket client disconnected")
    except Exception as e:
        audit.info(f"WebSocket error: {type(e).__name__} — {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": str(e),
            })
        except Exception:
            pass


def _execute_post_confirmation(name: str, args: dict, sentinel: str) -> str:
    """Execute actions that were approved through the confirmation gate."""
    from post_confirmation import execute_post_confirmation
    return execute_post_confirmation(name, args, sentinel)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = config.get("server.host", "0.0.0.0")
    port = config.get("server.port", 8420)

    print()
    print("  VYREN Web Server")
    print(f"  Tools: {len(registry.tool_names())} loaded")
    print(f"  Memory: {memory.count()} entries")
    print(f"  Dashboard: http://localhost:{port}")
    print()
    print("  For iPhone access:")
    print("    1. Quick:  ngrok http 8420  (gives you a public URL)")
    print("    2. Permanent: Cloudflare Tunnel")
    print("    3. Cloud: Deploy to Railway/Render + VPS")
    print()
    audit.info("Web server started")

    uvicorn.run(app, host=host, port=port, log_level="warning")