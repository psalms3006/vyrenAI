"""tools/file_manager_tools.py -- Universal Path Finder and File Operations."""

import json
import os
import shutil
from pathlib import Path
from typing import Optional, List
from tools import ToolDef, ToolRegistry

def register(registry: ToolRegistry):

    def find_file(name: str, root: Optional[str] = None, extension: Optional[str] = None) -> str:
        """Search for a file recursively by name and/or extension."""
        search_root = Path(root) if root else Path.cwd()
        matches = []
        
        ext_pattern = f"*{extension}" if extension else "*"
        if not ext_pattern.startswith("*"): ext_pattern = f"*{ext_pattern}"
            
        try:
            for path in search_root.rglob(ext_pattern):
                if name.lower() in path.name.lower():
                    matches.append(str(path))
                    if len(matches) >= 10: break # Cap results
            
            return json.dumps({
                "status": "success",
                "count": len(matches),
                "matches": matches
            })
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def read_file(path: str) -> str:
        """Read content of a file."""
        try:
            p = Path(path)
            if not p.exists():
                return json.dumps({"status": "error", "error": "File not found"})
            
            # Limit size to avoid context overflow (first 10k chars)
            content = p.read_text(encoding="utf-8", errors="replace")[:10000]
            return json.dumps({"status": "success", "path": path, "content": content})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def write_file(path: str, content: str) -> str:
        """Write content to a file."""
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return json.dumps({"status": "success", "path": path, "bytes": len(content)})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    def patch_file(path: str, search: str, replace: str) -> str:
        """Simple search and replace within a file."""
        try:
            p = Path(path)
            if not p.exists():
                return json.dumps({"status": "error", "error": "File not found"})
            content = p.read_text(encoding="utf-8")
            if search not in content:
                return json.dumps({"status": "error", "error": f"Search string not found in {path}"})
            new_content = content.replace(search, replace, 1)
            p.write_text(new_content, encoding="utf-8")
            return json.dumps({"status": "success", "path": path, "applied": True})
        except Exception as e:
            return json.dumps({"status": "error", "error": str(e)})

    registry.register(ToolDef(
        name="find_file",
        description="Recursively search for files by name or extension.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "root": {"type": "string"},
                "extension": {"type": "string"}
            },
            "required": ["name"]
        },
        handler=find_file
    ))

    registry.register(ToolDef(
        name="read_file",
        description="Read the contents of a file.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        },
        handler=read_file
    ))

    registry.register(ToolDef(
        name="write_file",
        description="Write new content to a file. Overwrites if exists.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        },
        handler=write_file,
        safety_level="consequential"
    ))

    registry.register(ToolDef(
        name="patch_file",
        description="Replace the first occurrence of 'search' with 'replace' in a file.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "search": {"type": "string"},
                "replace": {"type": "string"}
            },
            "required": ["path", "search", "replace"]
        },
        handler=patch_file,
        safety_level="consequential"
    ))
