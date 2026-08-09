import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from memory.obsidian_adapter import ObsidianSecondBrain


def make_vault(texts):
    root = Path(tempfile.mkdtemp(prefix="vyren-obsidian-"))
    for name, body in texts.items():
        p = root / name
        p.write_text(body, encoding="utf-8")
    return root


def test_entities_and_relations():
    root = make_vault({
        "NOVA.md": "# NOVA\nLinks [[Psalms]] and #ai #os\n",
        "VYREN.md": "[[NOVA]] uses [[Gemini Live]].\n",
        "ignore/.obsidian/workspace.json": "{}",
    })
    adapter = ObsidianSecondBrain(root)
    entities = adapter.entities()
    ids = [e.id for e in entities]
    assert any("NOVA" in i for i in ids)
    assert any("Gemini Live" in i for i in ids)
    assert any("ai" in i for i in ids)

    relations = adapter.relations()
    assert len(relations) >= 1
    payload = adapter.to_graph_payload()
    assert payload["stats"]["entities"] >= 3
    assert payload["stats"]["edges"] >= 1
