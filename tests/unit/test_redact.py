"""Tests for trajectory redaction."""

from __future__ import annotations

from ombench.traces.redact import Redactor


def test_redacts_email():
    r = Redactor()
    out, hits = r.redact_text("contact me at alice@example.com please")
    assert "alice@example.com" not in out
    assert "[REDACTED_EMAIL]" in out
    assert "email" in hits


def test_redacts_api_key():
    r = Redactor()
    out, hits = r.redact_text("token is xoxb-12345678-abcdefgh")
    assert "[REDACTED_SECRET]" in out
    assert "api_key" in hits


def test_redacts_phone():
    r = Redactor()
    out, hits = r.redact_text("call 415-555-1234 now")
    assert "[REDACTED_PHONE]" in out
    assert "phone" in hits


def test_recursive_redaction():
    r = Redactor()
    payload = {
        "user": {"email": "bob@corp.io", "name": "Bob"},
        "notes": ["reach at carol@x.com", "ok"],
    }
    redacted, hits = r.redact(payload)
    # "email" is not a redact key, so its value is scrubbed by the email pattern.
    assert redacted["user"]["email"] == "[REDACTED_EMAIL]"
    assert redacted["user"]["name"] == "Bob"
    assert "[REDACTED_EMAIL]" in redacted["notes"][0]
    assert redacted["notes"][1] == "ok"
    assert "email" in hits


def test_key_based_redaction():
    r = Redactor()
    redacted, hits = r.redact({"password": "hunter2", "ok": "value"})
    assert redacted["password"] == "[REDACTED]"
    assert redacted["ok"] == "value"
    assert "key:password" in hits


def test_clean_text_unchanged():
    r = Redactor()
    out, hits = r.redact_text("nothing sensitive here")
    assert out == "nothing sensitive here"
    assert hits == set()


def test_non_string_values_pass_through():
    r = Redactor()
    redacted, hits = r.redact({"count": 42, "flag": True, "nothing": None})
    assert redacted == {"count": 42, "flag": True, "nothing": None}
    assert hits == set()


def test_redacts_numeric_card_value():
    # A card-like number stored as an int should be redacted, not slip through.
    r = Redactor()
    redacted, hits = r.redact({"card": 4111111111111111})
    assert redacted["card"] == "[REDACTED_CARD]"
    assert "credit_card" in hits


def test_booleans_not_redacted():
    r = Redactor()
    redacted, hits = r.redact({"flag": True, "count": 3})
    assert redacted["flag"] is True
    assert redacted["count"] == 3
