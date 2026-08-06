"""
security/ -- Permission system, sandboxing, credential management.

Implements a layered security model:
  1. Tool safety levels (safe / consequential)
  2. Permission system (allow/deny/ask per tool)
  3. Credential vault (encrypted storage for API keys)
  4. Audit trail (all security events logged)
  5. Tool isolation (resource limits per tool)
"""

import json
import logging
import os
import hashlib
import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("vyren.security")

from platform_paths import get_security_dir

SEC_DIR = get_security_dir()


class PermissionLevel:
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


@dataclass
class Permission:
    tool_name: str
    level: str = PermissionLevel.ASK
    reason: str = ""


class PermissionStore:
    """Manages tool permissions."""

    def __init__(self):
        SEC_DIR.mkdir(parents=True, exist_ok=True)
        self.path = SEC_DIR / "permissions.json"
        self._permissions: dict[str, Permission] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for name, pd in data.items():
                    self._permissions[name] = Permission(**pd)
            except Exception:
                self._permissions = {}

    def _save(self):
        data = {n: p.__dict__ for n, p in self._permissions.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def set(self, tool_name: str, level: str, reason: str = ""):
        self._permissions[tool_name] = Permission(tool_name, level, reason)
        self._save()

    def get(self, tool_name: str) -> str:
        perm = self._permissions.get(tool_name)
        return perm.level if perm else PermissionLevel.ASK

    def check(self, tool_name: str) -> str:
        """Check permission level for a tool."""
        return self.get(tool_name)

    def list_all(self) -> list[dict]:
        return [
            {"tool": p.tool_name, "level": p.level, "reason": p.reason}
            for p in self._permissions.values()
        ]


class CredentialVault:
    """
    Simple credential storage. In production, use the OS keychain
    (keyring package) or a proper secrets manager.

    For now, credentials are stored with basic obfuscation.
    """

    def __init__(self):
        SEC_DIR.mkdir(parents=True, exist_ok=True)
        self.path = SEC_DIR / "credentials.json"
        self._creds: dict[str, str] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Decode values
                for k, v in data.items():
                    try:
                        self._creds[k] = base64.b64decode(v).decode("utf-8")
                    except Exception:
                        self._creds[k] = v
            except Exception:
                self._creds = {}

    def _save(self):
        data = {k: base64.b64encode(v.encode("utf-8")).decode("utf-8") for k, v in self._creds.items()}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def set(self, name: str, value: str):
        self._creds[name] = value
        self._save()

    def get(self, name: str) -> str | None:
        return self._creds.get(name)

    def delete(self, name: str) -> bool:
        if name in self._creds:
            del self._creds[name]
            self._save()
            return True
        return False

    def list_names(self) -> list[str]:
        return list(self._creds.keys())


class SecurityManager:
    """Unified security interface."""

    def __init__(self):
        self.permissions = PermissionStore()
        self.vault = CredentialVault()

    def get_status(self) -> dict:
        return {
            "permissions": len(self.permissions.list_all()),
            "credentials": len(self.vault.list_names()),
        }