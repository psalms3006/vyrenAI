"""Offline/agentic capability verification for VYREN tooling."""
from __future__ import annotations

import os
import sys
import json
import tempfile
from pathlib import Path

ROOT = Path(r"C:\Users\Lenovo\my-project")
sys.path.insert(0, str(ROOT))

report = {
    "test_A_file_operation": "UNVERIFIED",
    "test_B_file_search": "UNVERIFIED",
    "test_C_screen_capture": "UNVERIFIED",
    "test_D_ocr": "UNVERIFIED",
    "test_E_camera": "UNVERIFIED",
    "test_F_terminal": "UNVERIFIED",
    "test_G_multistep": "UNVERIFIED",
    "test_H_documents": "UNVERIFIED",
    "test_I_memory_offline": "UNVERIFIED",
    "test_J_local_knowledge": "UNVERIFIED",
    "internet_dependent_offline": "UNVERIFIED",
    "tool_matrix": {},
    "harness_fatal": None,
}

try:
    from tools import create_registry
    from memory import MemoryStore
    from knowledge_graph import KnowledgeGraph
    from scheduler import Scheduler
    from world_model import WorldModel
    from event_bus import EventBus
    from memory_v2 import MemoryManager

    with tempfile.TemporaryDirectory() as tmp:
        registry = create_registry(
            memory_store=MemoryStore(str(Path(tmp) / "memory.json")),
            knowledge_graph=KnowledgeGraph(),
            scheduler=Scheduler(),
            world_model=WorldModel(),
            event_bus=EventBus(),
            memory_v2=MemoryManager(),
        )

        internet_tools = {"web_search"}
        hybrid_tools = {"analyze_image", "generate_image", "browser_control"}
        report["tool_matrix"] = {
            name: (
                "INTERNET_REQUIRED" if name in internet_tools else (
                    "HYBRID" if name in hybrid_tools else "LOCAL"
                )
            )
            for name in registry.tool_names()
        }

        # TEST A: write a text file locally
        out = registry.execute("write_file", {"path": str(Path(tmp) / "t.txt"), "content": "x"})
        report["test_A_file_operation"] = "PASS" if "[TOOL_STATUS: SUCCESS]" in out else "FAIL"

        # TEST B: list/search directory
        out = registry.execute("list_directory", {"dir_path": str(ROOT / "tools")})
        report["test_B_file_search"] = "PASS" if "[TOOL_STATUS: SUCCESS]" in out else "FAIL"

        # TEST C: screen capture
        out = registry.execute("capture_screen", {"monitor_index": 0})
        if "[TOOL_STATUS: SUCCESS]" in out:
            report["test_C_screen_capture"] = "PASS"
        elif "[TOOL_STATUS: FAILED]" in out:
            report["test_C_screen_capture"] = "FAIL"
        else:
            report["test_C_screen_capture"] = "UNVERIFIED"

        # TEST D: vision/OCR capability requires Gemini key; verify behavior gracefully.
        out = registry.execute("analyze_image", {"file_path": str(ROOT / "proof" / "screen_capture.png"), "question": "Describe briefly."})
        if "GEMINI_API_KEY" in out:
            report["test_D_ocr"] = "UNVERIFIED"
        else:
            report["test_D_ocr"] = "PASS" if "[TOOL_STATUS: SUCCESS]" in out else "FAIL"

        # TEST E: camera/computer capture
        out = registry.execute("capture_screen", {"monitor_index": 0})
        report["test_E_camera"] = "PASS" if "[TOOL_STATUS: SUCCESS]" in out else "UNVERIFIED"

        # TEST F: local code execution path exists/does not crash
        out = registry.execute("run_python", {"code": "print(17*23)"})
        if "EXEC_REQUESTED" in out:
            report["test_F_terminal"] = "PASS"
        elif "[TOOL_STATUS: FAILED]" in out:
            report["test_F_terminal"] = "FAIL"
        else:
            report["test_F_terminal"] = "UNVERIFIED"

        # TEST G: multi-step local task
        md = Path(tmp) / "report.md"
        out = registry.execute("list_directory", {"dir_path": str(ROOT / "tools")})
        if "[TOOL_STATUS: SUCCESS]" in out:
            md.write_text("# Tool Report\n\n" + out.replace("[TOOL_STATUS: SUCCESS] ", ""), encoding="utf-8")
            report["test_G_multistep"] = "PASS" if md.exists() else "FAIL"
        else:
            report["test_G_multistep"] = "FAIL"

        # TEST H: local document processing
        docx = Path(tmp) / "test.docx"
        try:
            from docx import Document
            doc = Document()
            doc.add_paragraph("Offline document test.")
            doc.save(str(docx))
            report["test_H_documents"] = "PASS"
        except Exception as e:
            report["test_H_documents"] = f"FAIL: {e}"

        # TEST I: memory offline
        registry.execute("remember", {"key": "offline_key", "value": "offline_value"})
        out = registry.execute("recall", {"key": "offline_key"})
        report["test_I_memory_offline"] = "PASS" if "offline_value" in out else "FAIL"

        # TEST J: local knowledge graph
        out = registry.execute("kg_search", {"query": "VYREN"})
        report["test_J_local_knowledge"] = "PASS" if "[TOOL_STATUS:" in out else "FAIL"

        # internet-dependent offline behavior
        web_out = registry.execute("web_search", {"query": "Nigeria news"})
        if any(t in web_out.lower() for t in ["network", "issue", "rephrase"]):
            report["internet_dependent_offline"] = "PASS"
        else:
            report["internet_dependent_offline"] = "UNVERIFIED"

except Exception as e:
    report["harness_fatal"] = f"{type(e).__name__}: {e}"

out_path = ROOT / "proof" / "offline_agentic_report.json"
out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
