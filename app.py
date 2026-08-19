"""P&G ár-figyelő – helyi webes felület (Flask).

Indítás:  python app.py     ->  http://127.0.0.1:5000
"""
from __future__ import annotations

import os
import sys
import threading
import webbrowser
from typing import Dict

from flask import Flask, jsonify, render_template, request, send_file

from pgscraper.brands import BRANDS, GROUPS, grouped
from pgscraper.runner import Job, start_job

app = Flask(__name__)
JOBS: Dict[str, Job] = {}
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kimenet")


@app.route("/")
def index():
    return render_template(
        "index.html",
        groups=[(g, [b for b in grouped().get(g, [])]) for g in GROUPS],
        total_brands=len(BRANDS),
    )


@app.post("/api/run")
def api_run():
    payload = request.get_json(force=True, silent=True) or {}
    options = {
        "stores": payload.get("stores") or [],
        "brands": payload.get("brands") or [],
        "with_details": bool(payload.get("with_details", True)),
        "delay": float(payload.get("delay", 0.35)),
        "workers": int(payload.get("workers", 5)),
        "max_per_brand": int(payload.get("max_per_brand", 0)),
        "dm_mode": payload.get("dm_mode", "auto"),
        "show_browser": bool(payload.get("show_browser", False)),
        "out_dir": OUT_DIR,
    }
    if not options["stores"]:
        return jsonify({"error": "Válassz legalább egy boltot."}), 400
    if not options["brands"]:
        return jsonify({"error": "Válassz legalább egy márkát."}), 400
    job = start_job(options, JOBS)
    return jsonify({"job": job.id})


@app.get("/api/status/<job_id>")
def api_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Ismeretlen futás."}), 404
    return jsonify(job.snapshot())


@app.get("/api/results/<job_id>")
def api_results(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Ismeretlen futás."}), 404
    return jsonify({"products": [p.to_dict() for p in job.products]})


@app.post("/api/stop/<job_id>")
def api_stop(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Ismeretlen futás."}), 404
    job.stop()
    return jsonify({"ok": True})


@app.get("/api/download/<job_id>")
def api_download(job_id: str):
    job = JOBS.get(job_id)
    if not job or not job.excel_path or not os.path.exists(job.excel_path):
        return jsonify({"error": "Még nincs kész az Excel."}), 404
    return send_file(job.excel_path, as_attachment=True,
                     download_name=os.path.basename(job.excel_path))


def main() -> None:
    port = int(os.environ.get("PORT", "5000"))
    url = "http://127.0.0.1:{}".format(port)
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and "--no-browser" not in sys.argv:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print("\n  P&G ár-figyelő fut:  {}\n  (leállítás: Ctrl+C)\n".format(url))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
