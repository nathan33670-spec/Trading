"""Extraction JSON et chaîne de repli des fournisseurs LLM (sans réseau)."""
import pytest

from app.analysis import llm


def test_extract_json_plain():
    assert llm.extract_json('{"signals": []}') == {"signals": []}


def test_extract_json_with_prose_and_fences():
    text = 'Voici ma réponse :\n```json\n{"agree": true, "conviction": 70}\n```\nBonne journée.'
    assert llm.extract_json(text) == {"agree": True, "conviction": 70}


def test_extract_json_invalid():
    assert llm.extract_json("pas de json ici") is None
    assert llm.extract_json("{cassé") is None


@pytest.fixture
def fake_providers(monkeypatch):
    """Rend gemini et claude_cli 'disponibles' avec des générateurs contrôlés."""
    calls = []

    def gen(name, output):
        def _g(prompt):
            calls.append(name)
            if isinstance(output, Exception):
                raise output
            return output
        return _g

    def setup(gemini_out, claude_out):
        monkeypatch.setitem(llm._AVAILABILITY, "gemini", lambda: True)
        monkeypatch.setitem(llm._AVAILABILITY, "claude_cli", lambda: True)
        monkeypatch.setitem(llm._AVAILABILITY, "anthropic", lambda: False)
        monkeypatch.setitem(llm._GENERATORS, "gemini", gen("gemini", gemini_out))
        monkeypatch.setitem(llm._GENERATORS, "claude_cli", gen("claude_cli", claude_out))
        return calls

    return setup


def test_first_available_provider_wins(fake_providers):
    calls = fake_providers('{"signals": []}', '{"never": true}')
    data, provider = llm.generate_json("prompt")
    assert provider == "gemini"
    assert data == {"signals": []}
    assert calls == ["gemini"]


def test_fallback_on_provider_error(fake_providers):
    calls = fake_providers(RuntimeError("quota dépassé"), '{"agree": true}')
    data, provider = llm.generate_json("prompt")
    assert provider == "claude_cli"
    assert data == {"agree": True}
    assert calls == ["gemini", "claude_cli"]


def test_fallback_on_unparseable_output(fake_providers):
    fake_providers("réponse sans json", '{"ok": 1}')
    data, provider = llm.generate_json("prompt")
    assert provider == "claude_cli"
    assert data == {"ok": 1}


def test_exclude_keeps_second_opinion_independent(fake_providers):
    calls = fake_providers('{"from": "gemini"}', '{"from": "claude"}')
    data, provider = llm.generate_json("prompt", exclude=("gemini",))
    assert provider == "claude_cli"
    assert calls == ["claude_cli"]


def test_no_provider_available(monkeypatch):
    for p in llm.PROVIDERS:
        monkeypatch.setitem(llm._AVAILABILITY, p, lambda: False)
    data, provider = llm.generate_json("prompt")
    assert data is None and provider == ""

    signals, analyst = llm.analyze_news([{"source": "t", "title": "x", "summary": ""}])
    assert signals == [] and analyst == ""


def test_analyze_news_parses_signals(fake_providers):
    fake_providers('{"signals": [{"asset": "NVDA", "asset_class": "stock", "direction": "buy", "conviction": 77, "rationale": "r"}]}', "")
    signals, analyst = llm.analyze_news([{"source": "t", "title": "NVIDIA earnings beat", "summary": ""}])
    assert analyst == "gemini"
    assert signals[0]["asset"] == "NVDA"


def test_commentary_fallback_without_provider(monkeypatch):
    for p in llm.PROVIDERS:
        monkeypatch.setitem(llm._AVAILABILITY, p, lambda: False)
    text = llm.write_commentary({"trades": 3, "win_rate": 66.7, "pnl": 42.0}, "weekly")
    assert "3 trades" in text
