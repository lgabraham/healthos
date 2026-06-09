"""The `healthos setup` wizard writes .env correctly without an editor."""

from __future__ import annotations

from healthos.setup_wizard import FIELDS, read_env, run_wizard, set_env_value

TEMPLATE = """# HealthOS config
# Comments must survive the wizard.
DATABASE_URL=postgresql+psycopg://me@localhost:5432/healthos
GARMIN_EMAIL=
GARMIN_PASSWORD=
EIGHT_SLEEP_EMAIL=old@example.com
EIGHT_SLEEP_PASSWORD=oldpass
WHOOP_CLIENT_ID=
WHOOP_CLIENT_SECRET=
GARMIN_TOKENSTORE=
TIMEZONE=America/Los_Angeles
"""


def _wizard(tmp_path, answers: dict[str, str]):
    """Run the wizard feeding canned answers keyed by env var."""
    env = tmp_path / ".env"
    env.write_text(TEMPLATE)
    order = [k for k, _, _ in FIELDS]
    it = iter(order)
    visible_calls: list[str] = []
    hidden_calls: list[str] = []

    def fake_input(prompt: str) -> str:
        key = next(it)
        visible_calls.append(key)
        return answers.get(key, "")

    def fake_getpass(prompt: str) -> str:
        key = next(it)
        hidden_calls.append(key)
        return answers.get(key, "")

    # Route by field type the same way the wizard does.
    def dispatch_input(prompt):
        return fake_input(prompt)

    def dispatch_getpass(prompt):
        return fake_getpass(prompt)

    run_wizard(env, input_fn=dispatch_input, getpass_fn=dispatch_getpass, echo=lambda *_: None)
    return env, visible_calls, hidden_calls


def test_blank_answer_keeps_existing(tmp_path):
    env, _, _ = _wizard(tmp_path, {"GARMIN_EMAIL": "me@example.com"})
    vals = read_env(env)
    assert vals["GARMIN_EMAIL"] == "me@example.com"
    assert vals["EIGHT_SLEEP_EMAIL"] == "old@example.com"  # untouched
    assert vals["EIGHT_SLEEP_PASSWORD"] == "oldpass"


def test_passwords_go_through_getpass(tmp_path):
    _, visible, hidden = _wizard(tmp_path, {})
    assert "GARMIN_PASSWORD" in hidden
    assert "WHOOP_CLIENT_SECRET" in hidden
    assert "GARMIN_PASSWORD" not in visible


def test_comments_and_other_keys_preserved(tmp_path):
    env, _, _ = _wizard(tmp_path, {"WHOOP_CLIENT_ID": "abc123"})
    text = env.read_text()
    assert "# Comments must survive the wizard." in text
    assert "TIMEZONE=America/Los_Angeles" in text
    assert read_env(env)["WHOOP_CLIENT_ID"] == "abc123"


def test_garmin_tokenstore_default_added(tmp_path):
    env, _, _ = _wizard(tmp_path, {})
    vals = read_env(env)
    assert vals["GARMIN_TOKENSTORE"].endswith(".healthos/garth")


def test_set_env_value_appends_missing_key():
    out = set_env_value("A=1\n", "NEW_KEY", "v")
    assert "NEW_KEY=v" in out
    assert "A=1" in out
