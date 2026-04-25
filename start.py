"""
Run both servers with: python start.py
  - FastAPI backend  → http://localhost:8000
  - Streamlit app    → http://localhost:8501
Press Ctrl+C to stop both.
"""
import subprocess
import sys
import os
import threading

ROOT    = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, "backend")

def stream(proc, prefix):
    for line in iter(proc.stdout.readline, b""):
        print(f"[{prefix}] {line.decode(errors='replace').rstrip()}", flush=True)

api = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app",
     "--host", "0.0.0.0", "--port", "8000", "--reload"],
    cwd=BACKEND,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

web = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "app.py",
     "--server.port", "8501"],
    cwd=ROOT,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)

threading.Thread(target=stream, args=(api, "API "), daemon=True).start()
threading.Thread(target=stream, args=(web, "WEB "), daemon=True).start()

print("=" * 55)
print("  FastAPI  →  http://localhost:8000")
print("  Streamlit →  http://localhost:8501")
print("  Press Ctrl+C to stop both.")
print("=" * 55)

try:
    api.wait()
    web.wait()
except KeyboardInterrupt:
    print("\nStopping...")
    api.terminate()
    web.terminate()
    try:
        api.wait(timeout=5)
        web.wait(timeout=5)
    except subprocess.TimeoutExpired:
        api.kill()
        web.kill()
    print("Stopped.")
