"""Backend entry point (also the PyInstaller entry for the packaged app)."""
import argparse
import os
import sys

if getattr(sys, "frozen", False):  # PyInstaller bundle
    sys.path.insert(0, os.path.dirname(sys.executable))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(os.environ.get("COC_MANAGER_PORT", "8765")))
    args = p.parse_args()
    from app.main import app  # noqa: E402
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
