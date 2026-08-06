"""
camera/__init__.py -- Camera Engine package.

Public surface:
    CameraManager
    CameraInfo
    CameraMetrics
    CameraError
    CameraNotFoundError
    HAS_CV2
"""

from camera.backends import HAS_CV2
from camera.manager import (
    CameraManager,
    CameraInfo,
    CameraMetrics,
    CameraError,
    CameraNotFoundError,
)

__all__ = [
    "CameraManager",
    "CameraInfo",
    "CameraMetrics",
    "CameraError",
    "CameraNotFoundError",
    "HAS_CV2",
]
