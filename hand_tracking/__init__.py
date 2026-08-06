"""
hand_tracking/__init__.py -- Hand tracking package.

Public surface:
    HandTrackingEngine
    HandTrackingConfig
    HandBackend
    SyntheticHandBackend
    MediaPipeHandBackend
    GestureRecognizer
    GestureEvent
    Hand
    HandLandmark
    GestureType
"""
from hand_tracking.core import (
    GestureEvent,
    GestureRecognizer,
    GestureType,
    Hand,
    HandLandmark,
    HandBackend,
    MediaPipeHandBackend,
    SyntheticHandBackend,
)
from hand_tracking.engine import HandTrackingEngine, HandTrackingConfig

__all__ = [
    "HandTrackingEngine",
    "HandTrackingConfig",
    "HandBackend",
    "SyntheticHandBackend",
    "MediaPipeHandBackend",
    "GestureRecognizer",
    "GestureEvent",
    "Hand",
    "HandLandmark",
    "GestureType",
]
