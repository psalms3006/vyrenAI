"""Service registry and discovery for the VYREN runtime."""
from __future__ import annotations

from typing import Any


class RuntimeServiceRegistry:
    """Holds running service instances and supports lookup by name."""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def register(self, name: str, instance: Any) -> None:
        self._services[name] = instance

    def get(self, name: str, default: Any = None) -> Any:
        return self._services.get(name, default)

    def all(self) -> dict[str, Any]:
        return dict(self._services)

    def update(self, items: dict[str, Any]) -> None:
        self._services.update(items)

    def __setitem__(self, name: str, instance: Any) -> None:
        self._services[name] = instance

    def __getitem__(self, name: str) -> Any:
        return self._services[name]

    def __contains__(self, name: object) -> bool:
        return name in self._services

    def __iter__(self):
        return iter(self._services)

    def __len__(self) -> int:
        return len(self._services)
