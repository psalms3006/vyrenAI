"""
voice.py — Voice I/O primitives for VYREN.

This file provides the LOW-LEVEL building blocks:
  - transcribe()  — audio -> text (Deepgram STT)
  - synthesize()  — text -> audio (ElevenLabs TTS)
  - play_audio()  — audio bytes -> speakers
  - record_audio() — microphone -> audio bytes

The VOICE RUNTIME (voice/runtime.py) is the actual voice engine that
uses these primitives. It handles wake words, conversation mode,
Gemini Live Audio, and barge-in. This file is just the I/O layer.

Voice is VYREN's PRIMARY interface. These functions are always available.
"""

import asyncio
import io
import os
import tempfile
import threading
from typing import Callable

import httpx
import numpy as np


# ---------------------------------------------------------------------------
# Audio Recording
# ---------------------------------------------------------------------------

def record_audio(stop_event: threading.Event, sample_rate: int = 16000) -> np.ndarray:
    """Record audio from the default microphone until stop_event is set."""
    import sounddevice as sd

    frames = []

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    with sd.InputStream(samplerate=sample_rate, channels=1, dtype="int16", callback=callback):
        stop_event.wait()

    if not frames:
        return np.array([], dtype=np.int16)
    return np.concatenate(frames)


# ---------------------------------------------------------------------------
# Speech-to-Text (Deepgram — online)
# ---------------------------------------------------------------------------

async def transcribe(audio_data: np.ndarray, sample_rate: int = 16000) -> str:
    """Transcribe audio using Deepgram. Returns the transcript text."""
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPGRAM_API_KEY not set")

    audio_bytes = audio_data.astype(np.int16).tobytes()

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            "https://api.deepgram.com/v1/listen",
            headers={"Authorization": f"Token {api_key}"},
            content=audio_bytes,
            params={
                "model": "nova-2",
                "smart_format": "true",
                "sample_rate": sample_rate,
                "detect_language": "true",
            },
        )
        result = response.json()

    try:
        channel = result["results"]["channels"][0]
        return channel["alternatives"][0]["transcript"]
    except (KeyError, IndexError):
        return ""


# ---------------------------------------------------------------------------
# Text-to-Speech (ElevenLabs — online)
# ---------------------------------------------------------------------------

async def synthesize(text: str, voice_id: str | None = None) -> bytes:
    """Synthesize speech using ElevenLabs. Returns MP3 bytes."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise EnvironmentError("ELEVENLABS_API_KEY not set")

    if not voice_id:
        voice_id = os.environ.get("VYREN_VOICE", "21m00Tcm4TlvDq8ikWAM")  # Rachel

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            },
        )
        return response.content


# ---------------------------------------------------------------------------
# Audio Playback
# ---------------------------------------------------------------------------

def play_audio(mp3_data: bytes):
    """Play MP3 audio data through the speakers. Blocking."""
    try:
        from pydub import AudioSegment
        import sounddevice as sd

        audio = AudioSegment.from_mp3(io.BytesIO(mp3_data))
        samples = np.array(audio.get_array_of_samples(), dtype=np.int16)
        if audio.channels == 2:
            samples = samples.reshape((-1, 2))
        sd.play(samples, samplerate=audio.frame_rate)
        sd.wait()

    except ImportError:
        try:
            import pygame
            pygame.mixer.init()
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp.write(mp3_data)
            tmp.close()
            pygame.mixer.music.load(tmp.name)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.Clock().tick(10)
            os.unlink(tmp.name)
            pygame.mixer.quit()
        except Exception:
            print("\n[Cannot play audio: install pydub or pygame]\n")