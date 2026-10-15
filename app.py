"""Vocal remover: upload a song, get a karaoke instrumental and isolated vocals.

Runs Demucs (Meta's open-source source-separation model) on the machine this
file runs on. Start with:  python app.py   then open http://localhost:5000
"""
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

BASE = Path(__file__).parent
WORK = BASE / "jobs"

ALLOWED = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".webm", ".mp4", ".mkv", ".mov"}
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "100"))
MODEL = os.environ.get("DEMUCS_MODEL", "htdemucs")
DEVICE = os.environ.get("DEMUCS_DEVICE")  # e.g. "cuda", "mps", "cpu"; default = auto
HOST = os.environ.get("HOST", "127.0.0.1")  # keep 127.0.0.1 unless you add your own login in front
PORT = int(os.environ.get("PORT", "5000"))
KEEP_SECONDS = 60 * 60  # finished results are deleted after one hour

# Start clean: remove anything left over from a previous run.
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir()

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024

jobs = {}
one_at_a_time = threading.Semaphore(1)  # separation is heavy; run one song at a time


def safe_name(name):
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name).strip()
    return cleaned[:120] or "song"


def cleanup_old_jobs():
    now = time.time()
    for job_id, job in list(jobs.items()):
        if job["status"] in ("done", "error") and now - job["finished"] > KEEP_SECONDS:
            shutil.rmtree(WORK / job_id, ignore_errors=True)
            jobs.pop(job_id, None)


def janitor():
    while True:
        time.sleep(300)
        cleanup_old_jobs()


def run_job(job_id, src):
    job = jobs[job_id]
    out_dir = WORK / job_id / "out"
    try:
        with one_at_a_time:
            job["status"] = "processing"
            cmd = [
                sys.executable, "-m", "demucs",
                "--two-stems=vocals", "--mp3", "--mp3-bitrate", "256",
                "-n", MODEL, "-o", str(out_dir), str(src),
            ]
            if DEVICE:
                cmd += ["-d", DEVICE]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 30)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or "Demucs failed").strip()[-400:])
            inst = next(out_dir.rglob("no_vocals.*"), None)
            voc = next(out_dir.rglob("vocals.*"), None)
            if not inst or not voc:
                raise RuntimeError("Demucs finished but no output files were found.")
            job["files"] = {"instrumental": inst, "vocals": voc}
            job["status"] = "done"
    except Exception as exc:  # report any failure back to the page
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        src.unlink(missing_ok=True)  # the original upload is no longer needed
        job["finished"] = time.time()


@app.after_request
def add_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    return resp


@app.errorhandler(413)
def too_large(_):
    return jsonify(error=f"That file is over {MAX_MB} MB. Choose a smaller one."), 413


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.post("/api/jobs")
def create_job():
    cleanup_old_jobs()
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify(error="No file was uploaded."), 400
    ext = Path(upload.filename).suffix.lower()
    if ext not in ALLOWED:
        return jsonify(error=f"Unsupported file type. Use {', '.join(sorted(ALLOWED))}."), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = WORK / job_id
    job_dir.mkdir()
    src = job_dir / f"input{ext}"
    upload.save(src)

    jobs[job_id] = {
        "status": "queued",
        "name": safe_name(Path(upload.filename).stem),
        "created": time.time(),
    }
    threading.Thread(target=run_job, args=(job_id, src), daemon=True).start()
    return jsonify(id=job_id), 202


@app.get("/api/jobs/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        abort(404)
    body = {"status": job["status"], "name": job["name"]}
    if job["status"] == "error":
        body["error"] = job["error"]
    return jsonify(body)


@app.get("/api/jobs/<job_id>/<stem>")
def job_file(job_id, stem):
    job = jobs.get(job_id)
    if not job or job["status"] != "done" or stem not in job["files"]:
        abort(404)
    path = job["files"][stem]
    label = "instrumental" if stem == "instrumental" else "vocals"
    return send_file(
        path,
        mimetype="audio/mpeg",
        as_attachment=request.args.get("download") == "1",
        download_name=f"{job['name']} ({label}){path.suffix}",
        conditional=True,  # lets the browser seek inside the audio
    )


if __name__ == "__main__":
    threading.Thread(target=janitor, daemon=True).start()
    print(f"Vocal remover running at http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)
