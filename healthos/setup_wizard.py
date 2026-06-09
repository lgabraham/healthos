"""Interactive credential setup: ``healthos setup``.

A guided wizard that writes .env for you — no text editor needed. For each
credential it shows whether a value is already set (never the value itself),
lets Enter keep it, and hides password input. Comments and unrelated lines in
.env are preserved.
"""

from __future__ import annotations

import getpass
import re
import shutil
from pathlib import Path

# (env key, prompt label, hidden input?)
FIELDS: list[tuple[str, str, bool]] = [
    ("GARMIN_EMAIL", "Garmin email", False),
    ("GARMIN_PASSWORD", "Garmin password", True),
    ("EIGHT_SLEEP_EMAIL", "Eight Sleep email", False),
    ("EIGHT_SLEEP_PASSWORD", "Eight Sleep password", True),
    ("WHOOP_CLIENT_ID", "Whoop client ID (from developer.whoop.com)", False),
    ("WHOOP_CLIENT_SECRET", "Whoop client secret", True),
]

GARTH_DIR = Path.home() / ".healthos" / "garth"


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def set_env_value(text: str, key: str, value: str) -> str:
    """Replace ``key``'s line in-place, or append it, preserving everything else."""
    pattern = re.compile(rf"(?m)^{re.escape(key)}=.*$")
    if pattern.search(text):
        return pattern.sub(lambda _m: f"{key}={value}", text)
    if not text.endswith("\n"):
        text += "\n"
    return text + f"{key}={value}\n"


def run_wizard(
    env_path: Path | None = None,
    input_fn=input,
    getpass_fn=getpass.getpass,
    echo=print,
) -> Path:
    """Prompt for each credential and write .env. Returns the path written.

    ``input_fn``/``getpass_fn``/``echo`` are injectable for tests.
    """
    path = env_path or Path(".env")
    if not path.exists():
        example = path.with_name(".env.example")
        if example.exists():
            shutil.copy(example, path)
            echo(f"Created {path} from {example.name}.")
        else:
            path.touch()

    current = read_env(path)
    text = path.read_text()

    echo("\nHealthOS setup — Enter keeps the existing value; passwords are hidden.\n")
    for key, label, hidden in FIELDS:
        existing = current.get(key, "")
        state = f"set, {len(existing)} chars" if existing else "empty"
        prompt = f"  {label} [{state}]: "
        raw = (getpass_fn(prompt) if hidden else input_fn(prompt)).strip()
        if raw:
            text = set_env_value(text, key, raw)

    # Cache Garmin sessions so repeated logins don't trip Garmin's rate limits.
    if not current.get("GARMIN_TOKENSTORE"):
        GARTH_DIR.mkdir(parents=True, exist_ok=True)
        text = set_env_value(text, "GARMIN_TOKENSTORE", str(GARTH_DIR))
        echo(f"  Garmin session cache -> {GARTH_DIR} (avoids 429 rate limits)")

    path.write_text(text)
    echo(f"\nSaved {path}. Next: run `healthos doctor` to verify connections.")
    return path
