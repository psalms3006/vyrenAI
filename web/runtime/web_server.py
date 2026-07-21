"""
runtime/web_server.py -- Web Server wrapper for Runtime Manager.

Wraps the FastAPI server so it can be started and stopped by the
Runtime Manager instead of running standalone via `python server.py`.

Reuses the same endpoints and WebSocket logic but uses the shared
VYREN context (no duplicated initialization).
"""

import asyncio
import json
import logging
import os
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse

logger = logging.getLogger("vyren.server")


class WebServer:
    """
    Manages the FastAPI web server lifecycle.

    Started and stopped by the Runtime Manager.
    Uses the shared context for all subsystem access.
    """

    def __init__(self, ctx: dict):
        self._ctx = ctx
        self._app: FastAPI | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._host = "0.0.0.0"
        self._port = 8420
        self._running = False

        # Web directory
        self._web_dir = Path(__file__).parent.parent / "web"

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def port(self) -> int:
        return self._port

    def start(self):
        """Start the web server in a background thread."""
        import config

        self._host = config.get("server.host", "0.0.0.0")
        self._port = config.get("server.port", 8420)
        self._running = True

        self._app = self._create_app()

        config_uv = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config_uv)

        self._thread = threading.Thread(
            target=self._run_server,
            name="vyren-web-server",
            daemon=True,
        )
        self._thread.start()

        # Store port in context for other services
        self._ctx["server_port"] = self._port

        logger.info(f"Web server starting on {self._host}:{self._port}")

        # Wait briefly for server to be ready
        for _ in range(20):
            if self._server.started:
                break
            time.sleep(0.25)
        else:
            logger.warning("Web server may not have started in time")

    def stop(self):
        """Stop the web server."""
        if self._server:
            self._server.should_exit = True
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Web server stopped")

    def _run_server(self):
        """Run the uvicorn server (blocking, in background thread)."""
        try:
            self._server.run()
        except Exception as e:
            logger.error(f"Web server error: {e}")
            self._running = False

    def _create_app(self) -> FastAPI:
        """Create the FastAPI application with all routes."""
        app = FastAPI(title="VYREN")

        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        ctx = self._ctx

        # -- PWA + Static Files --

        @app.get("/")
        async def dashboard():
            return HTMLResponse(
                (self._web_dir / "index.html").read_text(encoding="utf-8")
            )

        @app.get("/manifest.json")
        async def manifest():
            return FileResponse(
                self._web_dir / "manifest.json",
                media_type="application/json",
            )

        @app.get("/sw.js")
        async def service_worker():
            return FileResponse(
                self._web_dir / "sw.js",
                media_type="application/javascript",
            )

        # -- REST API --

        @app.get("/api/system")
        async def system_stats():
            mem = psutil.virtual_memory()
            disk_root = "C:\\" if platform.system() == "Windows" else "/"
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

            connectivity = ctx.get("connectivity")
            conn_status = "unknown"
            if connectivity:
                conn_status = connectivity.mode.value

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
                "tool_count": len(ctx.get("registry", type('o', (), {'tool_names': lambda: []})()).tool_names()),
                "memory_entries": ctx["memory"].count() if ctx.get("memory") else 0,
                "ollama_available": connectivity.ollama_available if connectivity else False,
                "connectivity": conn_status,
                "voice_active": (ctx.get("voice_runtime") and ctx["voice_runtime"].is_active) or False,
            }

        @app.get("/api/memory")
        async def get_memory():
            mem = ctx.get("memory")
            if mem:
                return mem.list_all()
            return []

        @app.get("/api/tools")
        async def get_tools():
            reg = ctx.get("registry")
            if reg:
                return [
                    {
                        "name": t.name,
                        "description": t.description[:100],
                        "safety_level": t.safety_level,
                    }
                    for t in reg.all_tools()
                ]
            return []

        @app.get("/api/audit")
        async def get_audit(limit: int = 50):
            audit = ctx.get("audit")
            if not audit:
                return {"entries": []}
            try:
                with open(audit.path, "r") as f:
                    lines = f.readlines()
                recent = [l.strip() for l in lines[-limit:] if l.strip()]
                return {"entries": recent}
            except Exception:
                return {"entries": []}

        @app.get("/api/notices")
        async def get_notices():
            ns = ctx.get("notice_store")
            if ns:
                return {"pending": ns.get_pending()}
            return {"pending": []}

        @app.post("/api/notices/{notice_id}/dismiss")
        async def dismiss_notice(notice_id: str):
            ns = ctx.get("notice_store")
            success = ns.dismiss(notice_id) if ns else False
            return {"dismissed": success}

        @app.get("/api/heartbeat")
        async def heartbeat_status():
            hb = ctx.get("heartbeat")
            if hb:
                return hb.get_status()
            return {"running": False}

        @app.get("/api/connectivity")
        async def connectivity_status():
            cm = ctx.get("connectivity")
            if cm:
                s = cm.status
                return {
                    "mode": s.mode.value,
                    "internet": s.internet_available,
                    "gemini": s.gemini_available,
                    "ollama": s.ollama_available,
                    "latency_ms": s.latency_ms,
                }
            return {"mode": "unknown"}

        @app.get("/api/agents")
        async def agents_status():
            coord = ctx.get("coordinator")
            if coord:
                return coord.get_status()
            return {"registered_agents": 0}

        @app.get("/api/voice")
        async def voice_status():
            vr = ctx.get("voice_runtime")
            if vr:
                return {
                    "active": vr.is_active,
                    "mode": vr.mode,
                    "wake_word": vr.wake_word,
                }
            return {"active": False}

        # -- WebSocket Chat --
        @app.websocket("/ws/chat")
        async def chat(websocket: WebSocket):
            await websocket.accept()
            history: list[dict] = []
            audit = ctx.get("audit")
            if audit:
                audit.info("WebSocket client connected")

            try:
                while True:
                    data = json.loads(await websocket.receive_text())

                    if data.get("type") == "message":
                        text = data["text"].strip().lower()
                        import safety

                        if text == "/kill":
                            safety.activate_kill_switch()
                            await websocket.send_json({
                                "type": "system_msg",
                                "system_msg": "Kill switch activated.",
                            })
                            if audit:
                                audit.security("Kill switch activated (web)")
                            continue
                        elif text == "/unkill":
                            safety.deactivate_kill_switch()
                            await websocket.send_json({
                                "type": "system_msg",
                                "system_msg": "Kill switch deactivated.",
                            })
                            continue
                        elif text == "/tools":
                            reg = ctx.get("registry")
                            if reg:
                                tools_info = "\n".join(
                                    f"  {t.name} [{t.safety_level}] -- {t.description[:60]}"
                                    for t in reg.all_tools()
                                )
                                await websocket.send_json({
                                    "type": "system_msg",
                                    "system_msg": f"Tools ({len(reg.tool_names())}):\n{tools_info}",
                                })
                            continue
                        elif text == "/memory":
                            mem = ctx.get("memory")
                            if mem:
                                facts = mem.list_all()
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
                            continue

                    if data.get("type") != "message":
                        continue

                    user_text = data["text"].strip()
                    if not user_text:
                        continue

                    history.append({"role": "user", "parts": [{"text": user_text}]})
                    if audit:
                        audit.model_turn("user", user_text)

                    # Stream response
                    from provider import run_turn

                    chunk_queue: asyncio.Queue[str | None] = asyncio.Queue()
                    loop = asyncio.get_event_loop()
                    system_prompt = ctx.get("system_prompt", "")
                    gemini_tools = ctx.get("gemini_tools", [])

                    def make_on_chunk(q: asyncio.Queue) -> callable:
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

                    on_chunk = make_on_chunk(chunk_queue)
                    sender = asyncio.create_task(stream_chunks(chunk_queue))
                    try:
                        result = await loop.run_in_executor(
                            None, run_turn, history, system_prompt,
                            gemini_tools, on_chunk
                        )
                    finally:
                        chunk_queue.put_nowait(None)
                        await asyncio.sleep(0.1)
                        sender.cancel()

                    # Tool calling loop
                    registry = ctx.get("registry")
                    import safety

                    max_rounds = 10
                    for _ in range(max_rounds):
                        if not result.function_calls or not registry:
                            break

                        model_parts = []
                        if result.text:
                            model_parts.append({"text": result.text})
                        for fc in result.function_calls:
                            model_parts.append({
                                "function_call": {"name": fc.name, "args": fc.args}
                            })
                        history.append({"role": "model", "parts": model_parts})

                        # Check consequential tools
                        confirmations: dict[str, bool] = {}
                        for fc in result.function_calls:
                            if registry.is_consequential(fc.name):
                                await websocket.send_json({
                                    "type": "confirmation_required",
                                    "name": fc.name,
                                    "args": fc.args,
                                })
                                try:
                                    resp = json.loads(await asyncio.wait_for(
                                        websocket.receive_text(), timeout=120
                                    ))
                                    approved = resp.get("approved", False)
                                except asyncio.TimeoutError:
                                    approved = False
                                confirmations[fc.name] = approved
                                if audit:
                                    audit.confirmation(fc.name, fc.args, approved)

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

                            if audit:
                                audit.info(f"Executing tool: {fc.name}")
                            tool_output = registry.execute(fc.name, fc.args)
                            if audit:
                                audit.tool_call(fc.name, fc.args, tool_output[:100])

                            # Handle sentinel values
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

                        # Next model turn
                        next_queue: asyncio.Queue[str | None] = asyncio.Queue()
                        next_on_chunk = make_on_chunk(next_queue)
                        sender = asyncio.create_task(stream_chunks(next_queue))
                        try:
                            result = await loop.run_in_executor(
                                None, run_turn, history, system_prompt,
                                gemini_tools, next_on_chunk
                            )
                        finally:
                            next_queue.put_nowait(None)
                            await asyncio.sleep(0.1)
                            sender.cancel()

                    if result.text:
                        history.append({"role": "model", "parts": [{"text": result.text}]})
                        if audit:
                            audit.model_turn("model", result.text)

                    await websocket.send_json({"type": "done"})

            except WebSocketDisconnect:
                if audit:
                    audit.info("WebSocket client disconnected")
            except Exception as e:
                if audit:
                    audit.info(f"WebSocket error: {type(e).__name__} -- {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                    })
                except Exception:
                    pass

        return app


def _execute_post_confirmation(name: str, args: dict, sentinel: str) -> str:
    """Execute actions that were approved through the confirmation gate."""
    try:
        if name == "shutdown_system":
            import subprocess
            subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
            return "Shutdown initiated."
        elif name == "restart_system":
            import subprocess
            subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
            return "Restart initiated."
        elif name == "delete_file":
            path = args.get("file_path", "")
            os.remove(path)
            return f"Deleted: {path}"
        elif name == "edit_file":
            path = args.get("file_path", "")
            content = args.get("content", "")
            resolved = os.path.realpath(path)
            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)
            lines = content.count("\n") + 1
            return f"File written: {resolved} ({lines} lines)"
        elif name == "run_python":
            import subprocess
            code = args.get("code", "")
            timeout = args.get("timeout", 30)
            python_exe = sys.executable or "python"
            result = subprocess.run(
                [python_exe, "-c", code],
                capture_output=True, text=True, timeout=timeout
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return output if output.strip() else "(no output)"
        else:
            return sentinel
    except Exception as e:
        return f"Error executing {name}: {type(e).__name__} -- {e}"