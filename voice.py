"""
voice.py — Voice I/O for VYREN (Tier 3).

Two voice paths:
  1. Browser voice — Web Speech API, works in the dashboard, zero setup.
     This is implemented in the dashboard HTML, not here.
  2. Terminal voice — Push-to-talk with Deepgram STT + ElevenLabs TTS.
     Requires API keys and optional packages (sounddevice, numpy).

This file implements #2 (terminal voice). It's optional — if the
dependencies or API keys aren't available, voice gracefully disables
itself and the text path keeps working.
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
# Availability check
# ---------------------------------------------------------------------------

def voice_available() -> dict:
    """Check what voice capabilities are available. Returns a dict."""
    result = {"stt": False, "tts": False, "recording": False, "reason": ""}

    # Check API keys
    if os.environ.get("DEEPGRAM_API_KEY"):
        result["stt"] = True
    else:
        result["reason"] += "No DEEPGRAM_API_KEY. "

    if os.environ.get("ELEVENLABS_API_KEY"):
        result["tts"] = True
    else:
        result["reason"] += "No ELEVENLABS_API_KEY. "

    # Check sounddevice
    try:
        import sounddevice as sd
        result["recording"] = True
    except ImportError:
        result["reason"] += "sounddevice not installed (pip install sounddevice). "

    result["ready"] = result["stt"] and result["tts"] and result["recording"]
    return result


# ---------------------------------------------------------------------------
# Audio Recording (push-to-talk)
# ---------------------------------------------------------------------------

def record_audio(stop_event: threading.Event, sample_rate: int = 16000) -> np.ndarray:
    """Record audio from the default microphone until stop_event is set.

    Returns a numpy int16 array of the recorded audio.
    """
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
# Speech-to-Text (Deepgram)
# ---------------------------------------------------------------------------

async def transcribe(audio_data: np.ndarray, sample_rate: int = 16000) -> str:
    """Transcribe audio using Deepgram. Returns the transcript text."""
    api_key = os.environ.get("DEEPGRAM_API_KEY")
    if not api_key:
        raise EnvironmentError("DEEPGRAM_API_KEY not set")

    # Convert numpy int16 array to raw bytes
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
# Text-to-Speech (ElevenLabs)
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
        sd.wait()  # Blocking until playback finishes

    except ImportError:
        # pydub not available — try pygame
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
            print("\n[Cannot play audio: install pydub (pip install pydub) "
                  "or pygame (pip install pygame)]\n")


# ---------------------------------------------------------------------------
# Push-to-talk loop (terminal)
# ---------------------------------------------------------------------------

def push_to_talk_loop(agent_process: Callable[[str], None],
                     on_transcript: Callable[[str], None] | None = None):
    """Run a push-to-talk loop. Hold SPACE to record, release to send.

    agent_process: function that takes a text string and processes it
                   (same as typing a message in the terminal).
    on_transcript: optional callback with the transcript text (for display).
    """
    import threading
    import sounddevice as sd
    from pynput import keyboard

    print("\n  VOICE MODE ACTIVE — Hold SPACE to talk, release to send.")
    print("  Press /text to switch back to typing. Ctrl+C to quit.\n")

    stop_event = threading.Event()
    should_process = threading.Event()
    current_text = [""]

    def on_press(key):
        if key == keyboard.Key.space and not stop_event.is_set():
            stop_event.clear()
            should_process.clear()
            print("  Recording...", end="", flush=True)
            # Start recording in a thread
            threading.Thread(
                target=_record_and_transcribe,
                args=(stop_event, should_process, current_text, on_transcript),
                daemon=True,
            ).start()

    def on_release(key):
        if key == keyboard.Key.space:
            stop_event.set()
            # Wait for transcription to finish
            should_process.wait(timeout=15)
            text = current_text[0].strip()
            if text:
                print(f"\r  You (voice): {text}\n")
                print("  VYREN: ", end="", flush=True)
                agent_process(text)
                print()
            else:
                print("\r  (no speech detected)\n")

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    try:
        # Keep alive until keyboard interrupt
        while True:
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()


def _record_and_transcribe(stop_event, should_process, current_text, on_transcript):
    """Record audio and transcribe it. Runs in a background thread."""
    try:
        audio = record_audio(stop_event)
        if len(audio) < 100:  # Too short
            should_process.set()
            return

        # Run transcription in the event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            text = loop.run_until_complete(transcribe(audio))
        finally:
            loop.close()

        current_text[0] = text
        if on_transcript and text:
            on_transcript(text)
    except Exception as e:
        print(f"\n  Voice error: {e}\n")
    finally:
        should_process.set()