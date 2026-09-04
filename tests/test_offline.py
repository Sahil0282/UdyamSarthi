"""Phase 7 — the offline district bundle.

Everything except the LLM call must work with no internet. This is not a
rhetorical claim: the test physically blocks every non-loopback socket, then
runs the full pipeline. If any engine reaches for the network it fails here.
"""
import socket

import pytest

_real_socket = socket.socket
_real_create = socket.create_connection


class _Blocked(OSError):
    pass


def _is_local(addr) -> bool:
    try:
        host = addr[0]
    except Exception:
        return False
    return host in ("127.0.0.1", "::1", "localhost", "0.0.0.0")


@pytest.fixture
def no_internet(monkeypatch):
    """Allow loopback (PostGIS on localhost), block everything else."""
    class Sock(_real_socket):
        def connect(self, addr):
            if not _is_local(addr):
                raise _Blocked(f"network blocked: {addr}")
            return super().connect(addr)

        def connect_ex(self, addr):
            if not _is_local(addr):
                raise _Blocked(f"network blocked: {addr}")
            return super().connect_ex(addr)

    def create_connection(addr, *a, **kw):
        if not _is_local(addr):
            raise _Blocked(f"network blocked: {addr}")
        return _real_create(addr, *a, **kw)

    monkeypatch.setattr(socket, "socket", Sock)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    yield


def test_full_advice_works_offline(no_internet):
    from core.pipeline import advise
    env = advise(village="nimgaon jali", capital_inr=100_000, sector="dairy")
    assert env["decision"]["verdict"] == "PROCEED"
    assert env["market"]["catchment_population"].value == 37123
    assert len(env["provenance"]) > 30


def test_refusal_works_offline(no_internet):
    from core.pipeline import advise
    env = advise(village="murmi", capital_inr=25_000, sector="dairy")
    assert env["decision"]["verdict"] == "RECONSIDER"
    assert env["decision"]["alternatives"]


def test_template_narration_works_offline(no_internet):
    from core.narrate import render_template
    from core.pipeline import advise
    env = advise(village="nimgaon jali", capital_inr=100_000, sector="dairy")
    for lang in ("en", "mr"):
        text = render_template(env, lang)
        assert len(text) > 200


def test_plp_retrieval_works_offline(no_internet):
    """RAG uses a local model over a saved matrix, so it must not need the net."""
    from core import plp
    if not plp.available():
        pytest.skip("PLP index not built (run etl/60_plp_embed.py)")
    hits = plp.by_section(["2.1.6"])
    assert hits and hits[0]["page"] > 1


def test_llm_is_the_only_thing_that_needs_the_network(no_internet):
    from core.narrate import narrate
    from core.pipeline import advise
    env = advise(village="nimgaon jali", capital_inr=100_000, sector="dairy")
    r = narrate(env, use_llm=True)          # will fail: no network
    assert r["path"] == "template", "LLM failure must fall back, not crash"
    assert r.get("fallback_reason") == "llm_call_failed"
    assert r["text"] == narrate(env, use_llm=False)["text"]


def test_voice_degrades_offline(no_internet):
    from core.voice import synthesize, transcribe
    assert synthesize("नमस्कार")["ok"] is False
    assert transcribe(b"\x00" * 100)["ok"] is False
