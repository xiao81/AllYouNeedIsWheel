"""Persist connection profiles atomically, retaining compatibility with JSON configs."""

import json
import hashlib
import os
import tempfile
from pathlib import Path

SETTINGS_PATH = Path(os.environ.get("WHEEL_SETTINGS_PATH", "settings.json"))


def read_profiles():
    if SETTINGS_PATH.exists():
        return json.loads(SETTINGS_PATH.read_text())
    profiles = {}
    for mode, filename, port in [
        ("paper", "connection.json", 7497),
        ("live", "connection_real.json", 7496),
    ]:
        profile = {
            "host": "127.0.0.1",
            "port": port,
            "client_id": 1,
            "readonly": True,
            "account_id": "",
            "db_path": f"options_{mode}.db",
            "platform": "tws",
        }
        path = Path(filename)
        if path.exists():
            profile.update(json.loads(path.read_text()))
        profiles[mode] = profile
    mode = (
        "live"
        if os.environ.get("CONNECTION_CONFIG") == "connection_real.json"
        else "paper"
    )
    return {"mode": mode, **profiles}


def save_profiles(data):
    if not isinstance(data, dict) or data.get("mode") not in ("paper", "live"):
        raise ValueError("Choose Paper or Live mode")
    current = read_profiles()
    for mode in ("paper", "live"):
        values = data.get(mode)
        if not isinstance(values, dict):
            raise ValueError(f"Missing {mode} connection settings")
        profile = current[mode].copy()
        host = str(values.get("host", "")).strip()
        if not host or len(host) > 253 or any(c.isspace() for c in host):
            raise ValueError("Enter a valid broker host")
        for field, minimum, maximum in [
            ("port", 1, 65535),
            ("client_id", 1, 2147483647),
        ]:
            value = values.get(field)
            if (
                isinstance(value, bool)
                or not str(value).isdigit()
                or not minimum <= int(value) <= maximum
            ):
                raise ValueError(f"Invalid {field.replace('_', ' ')}")
            profile[field] = int(value)
        if not isinstance(values.get("readonly"), bool):
            raise ValueError("Read-only setting must be true or false")
        platform = values.get("platform", "tws")
        if platform not in ("tws", "gateway"):
            raise ValueError("Choose TWS or IB Gateway")
        profile.update(
            host=host,
            readonly=values["readonly"],
            platform=platform,
            account_id=str(values.get("account_id") or "").strip(),
        )
        current[mode] = profile
    current["mode"] = data["mode"]
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=SETTINGS_PATH.parent, prefix=".settings-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(current, stream, indent=2)
        os.replace(temporary, SETTINGS_PATH)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return current


def public_profiles(profiles):
    fields = ("host", "port", "client_id", "readonly", "account_id", "platform")
    revision = hashlib.sha256(
        json.dumps(
            {"mode": profiles["mode"], "profile": profiles[profiles["mode"]]},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return {
        "mode": profiles["mode"],
        "revision": revision,
        **{
            mode: {key: profiles[mode].get(key) for key in fields}
            for mode in ("paper", "live")
        },
    }
