"""One-step launcher: sets everything up the first time, then just starts the app.

Double-click start.bat (Windows) or start.command (macOS), or run:  python run.py
You never need to create or activate a virtual environment yourself.
"""
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import venv
import webbrowser
from pathlib import Path

BASE = Path(__file__).resolve().parent
VENV = BASE / "venv"
PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MARKER = VENV / ".requirements-installed"
PORT = os.environ.get("PORT", "5000")
URL = f"http://localhost:{PORT}"


def stop(message):
    print("\n" + message)
    sys.exit(1)


def app_is_up():
    try:
        urllib.request.urlopen(URL, timeout=1)
        return True
    except Exception:
        return False


def ffmpeg_hint():
    if sys.platform == "darwin":
        return "Install it with:  brew install ffmpeg"
    if os.name == "nt":
        return "Install it with:  winget install ffmpeg   (then close and reopen this window)"
    return "Install it with:  sudo apt install ffmpeg"


def main():
    if app_is_up():
        print(f"Vocal remover is already running. Opening {URL}")
        webbrowser.open(URL)
        return

    if sys.version_info < (3, 9):
        stop("Python 3.9 or newer is needed. Please install a newer Python from python.org.")

    if not shutil.which("ffmpeg"):
        stop("ffmpeg is needed to read MP3, M4A and video files, but it was not found.\n" + ffmpeg_hint())

    if not PY.exists():
        print("First-time setup: creating a private Python environment...")
        venv.create(VENV, with_pip=True)

    wanted = (BASE / "requirements.txt").read_text()
    if not MARKER.exists() or MARKER.read_text() != wanted:
        print("Installing the vocal remover (first run only; this can take several minutes)...")
        result = subprocess.run([str(PY), "-m", "pip", "install", "-r", str(BASE / "requirements.txt")])
        if result.returncode != 0:
            stop(
                "The install did not finish. Check your internet connection and try again.\n"
                "If you use a very new Python version, installing Python 3.12 often fixes this."
            )
        MARKER.write_text(wanted)

    print("Starting the vocal remover. Keep this window open while you use it.")
    server = subprocess.Popen([str(PY), str(BASE / "app.py")], cwd=BASE)
    try:
        for _ in range(60):
            if server.poll() is not None:
                stop("The app stopped unexpectedly. See the messages above.")
            if app_is_up():
                break
            time.sleep(0.5)
        print(f"Ready at {URL}  (close this window or press Ctrl+C to stop)")
        webbrowser.open(URL)
        server.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if server.poll() is None:
            server.terminate()


if __name__ == "__main__":
    main()
