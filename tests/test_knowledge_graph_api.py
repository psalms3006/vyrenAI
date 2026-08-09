"""Knowledge graph API and visualization verification."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\Lenovo\my-project")
sys.path.insert(0, str(ROOT))

proof_dir = ROOT / "proof"
proof_dir.mkdir(exist_ok=True)
report_path = proof_dir / "knowledge_graph_report.json"
report = {"tests": [], "overall": "UNKNOWN"}


def case(name: str):
    def decorator(fn):
        def wrapper():
            try:
                ok, detail = fn()
            except Exception as exc:
                ok, detail = False, f"EXCEPTION: {type(exc).__name__}: {exc}"
            report["tests"].append({"case": name, "passed": ok, "detail": detail})
            print(f"{'PASS' if ok else 'FAIL'} | {name} | {detail}")
            return ok, detail
        return wrapper()
    return decorator


@case("graph_api_endpoints")
def _():
    from fastapi.testclient import TestClient
    from runtime.web_server import WebServer

    server = WebServer({})
    server._app = server._create_app()
    client = TestClient(server._app)
    response = client.get("/api/graph")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data
    assert "links" in data
    assert "stats" in data
    return True, f"status={response.status_code}, nodes={len(data['nodes'])}, links={len(data['links'])}"


@case("graph_search_endpoint")
def _():
    from fastapi.testclient import TestClient
    from runtime.web_server import WebServer

    server = WebServer({})
    server._app = server._create_app()
    client = TestClient(server._app)
    response = client.get("/api/graph/search?q=test&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "results" in data
    return True, f"status={response.status_code}, results={len(data['results'])}"


@case("graph_page_served")
def _():
    from fastapi.testclient import TestClient
    from runtime.web_server import WebServer

    server = WebServer({})
    server._app = server._create_app()
    client = TestClient(server._app)
    response = client.get("/graph")
    assert response.status_code == 200
    assert "vis-network" in response.text or "Knowledge Graph" in response.text
    return True, f"status={response.status_code}, html_len={len(response.text)}"


@case("graph_html_exists")
def _():
    path = ROOT / "web" / "graph.html"
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "vis-network" in text
    assert "api/graph" in text
    return True, f"file_exists={path.exists()}, size={len(text)}"


overall = "PASS"
for t in report["tests"]:
    if not t["passed"]:
        overall = "PARTIAL"
        break
report["overall"] = overall
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nOVERALL: {overall}")
print("proof:", report_path)
