import importlib
mods = [
    'PIL', 'cv2', 'numpy', 'mss', 'sounddevice', 'faster_whisper',
    'pyttsx3', 'playwright', 'easyocr', 'mediapipe', 'pyautogui',
    'pyperclip', 'psutil', 'httpx', 'fastapi', 'uvicorn', 'websockets',
    'yaml', 'dotenv', 'torch', 'transformers', 'sentence_transformers',
    'faiss', 'bs4', 'lxml', 'win32com', 'pynput', 'watchdog',
    'requests', 'packaging', 'comtypes', 'pygame', 'soundfile', 'pydub',
    'paddleocr',
]
for m in mods:
    try:
        importlib.import_module(m)
        print('OK', m)
    except Exception as e:
        print('FAIL', m, type(e).__name__, e)
