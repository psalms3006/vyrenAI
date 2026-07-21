"""test_tier2.py — Verify all Tier 2+4+6 components work together."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tools import create_registry
from memory import MemoryStore
from provider import run_turn, TurnResult, FunctionCall
from system_prompt import build_system_prompt

passed = 0
failed = 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")

# --- Config ---
import config
config.load()
check("config loads", config.get("model.name") == "gemini-2.5-flash")

# --- Memory ---
mem = MemoryStore(os.path.join(tempfile.gettempdir(), "test_vyren_t2.json"))
check("memory empty", mem.count() == 0)
mem.add("location", "Lagos, Nigeria")
check("memory add", mem.count() == 1)
check("memory get", mem.get("location") == "Lagos, Nigeria")
check("memory search", len(mem.search("lagos")) == 1)
check("memory context", "Lagos" in mem.build_context())
mem.delete("location")
check("memory delete", mem.count() == 0)

# --- Audit ---
from audit import AuditLog
audit = AuditLog(os.path.join(tempfile.gettempdir(), "test_vyren_audit.log"))
audit.info("test")
check("audit writes", os.path.exists(audit.path))

# --- Safety ---
import safety
safety.activate_kill_switch()
check("kill switch on", safety.is_killed())
safety.deactivate_kill_switch()
check("kill switch off", not safety.is_killed())

# --- Tool Registry ---
registry = create_registry(memory_store=mem)
names = registry.tool_names()
check(f"tools registered ({len(names)})", len(names) == 13)

check("safe tool flag", not registry.is_consequential("remember"))
check("safe tool flag 2", not registry.is_consequential("web_search"))
check("consequential flag", registry.is_consequential("shutdown_system"))
check("consequential flag 2", registry.is_consequential("delete_file"))

# --- Gemini Format ---
gt = registry.to_gemini_tools()
check("gemini tools format", len(gt) == 1 and len(gt[0].function_declarations) == 13)

# --- Tool Execution ---
r = registry.execute("remember", {"key": "city", "value": "Lagos"})
check("execute remember", "Remembered" in r)

r = registry.execute("recall", {"key": "city"})
check("execute recall", "Lagos" in r)

r = registry.execute("search_memory", {"query": "Lag"})
check("execute search_memory", "Lagos" in r)

r = registry.execute("list_memory", {})
check("execute list_memory", "city" in r)

r = registry.execute("delete_memory", {"key": "city"})
check("execute delete_memory", "Deleted" in r)

r = registry.execute("get_system_info", {})
check("execute get_system_info", "CPU" in r)

r = registry.execute("read_file", {"file_path": "/home/z/my-project/vyren/AGENT.md", "max_lines": 5})
check("execute read_file", "VYREN" in r)

r = registry.execute("list_directory", {"dir_path": "/home/z/my-project/vyren"})
check("execute list_directory", "main.py" in r)

r = registry.execute("fake_tool", {})
check("execute unknown tool", "Unknown tool" in r)

r = registry.execute("recall", {"wrong_arg": "x"})
check("execute wrong args", "Error" in r)

# --- Provider (no-key test) ---
history = [{"role": "user", "parts": [{"text": "hello"}]}]
result = run_turn(history, "You are a test assistant.", on_chunk=lambda t: None)
check("provider returns TurnResult", isinstance(result, TurnResult))
check("provider no-key yields error", "GEMINI_API_KEY" in result.text)

# --- System Prompt ---
prompt = build_system_prompt("User is in Lagos")
check("system prompt with memory", "Lagos" in prompt)
check("system prompt base", "VYREN" in prompt)

# --- Cleanup ---
os.unlink(mem.path)
os.unlink(audit.path)

print(f"\n{'='*40}")
print(f"  {passed} passed, {failed} failed")
print(f"{'='*40}")
sys.exit(1 if failed else 0)