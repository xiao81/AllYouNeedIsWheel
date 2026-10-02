"""Serve templates for browser tests using a temporary read-only configuration."""

import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import types

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
logging_stub = types.ModuleType("core.logging_config")
logging_stub.get_logger = lambda *args: logging.getLogger("preview")
sys.modules["core.logging_config"] = logging_stub
with tempfile.TemporaryDirectory() as temporary:
    os.chdir(temporary)
    Path("connection.json").write_text(
        json.dumps({"readonly": True, "db_path": "preview.db"})
    )
    from app import app
    from core.connection import IBConnection

    def blocked(*args, **kwargs):
        raise RuntimeError("Broker connections are disabled in the UI preview")

    IBConnection.connect = blocked
    app.run(host="127.0.0.1", port=8123, debug=False, use_reloader=False)
