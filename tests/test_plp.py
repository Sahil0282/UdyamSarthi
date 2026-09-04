"""Phase 7 — PLP retrieval must cite the right section or claim nothing."""
import glob

import pytest
import yaml

from core import plp
from core.pipeline import advise

pytestmark = pytest.mark.skipif(not plp.available(),
                                reason="PLP index not built — run etl/60_plp_embed.py")

EXPECTED = {
    "dairy_buffalo": "2.1.6",
    "backyard_poultry": "2.1.7",
    "goat_rearing": "2.1.8",
    "kirana_retail": "3.",
}


def _sectors():
    return {yaml.safe_load(open(f))["sector_id"]: yaml.safe_load(open(f))
            for f in sorted(glob.glob("data/sectors/*.yaml"))}


@pytest.mark.parametrize("sid,prefix", sorted(EXPECTED.items()))
def test_each_sector_cites_its_declared_plp_section(sid, prefix):
    c = plp.cite_sector(_sectors()[sid])
    assert c["available"] is True
    assert c["citations"], f"{sid} produced no citation"
    assert c["retrieval"] == "section", \
        f"{sid} fell back to semantic search; the declared section did not match"
    for cit in c["citations"]:
        assert cit["section"].startswith(prefix), \
            f"{sid} cited {cit['section']!r}, expected a {prefix} section"


def test_citations_carry_a_real_page_number():
    for sid, sec in _sectors().items():
        for cit in plp.cite_sector(sec)["citations"]:
            assert cit["page"] > 1, f"{sid} citation has no real page"
            assert "Ahilyanagar" in cit["document"]


def test_front_matter_is_never_cited():
    """Citing the PLP's boilerplate as sector backing would be worse than
    citing nothing."""
    for sid, sec in _sectors().items():
        for cit in plp.cite_sector(sec)["citations"]:
            assert cit["section"] != "front matter", f"{sid} cited boilerplate"


def test_plp_reaches_the_envelope_and_the_alternatives():
    env = advise(village="murmi", capital_inr=25_000, sector="dairy")
    assert env["plp"]["available"] is True
    assert env["plp"]["sector"]["citations"]
    for alt in env["decision"]["alternatives"]:
        assert "plp" in alt, "alternative carries no PLP block"


def test_ranker_degrades_when_the_index_is_absent(monkeypatch):
    """PART 3.4: with no PLP, rank on market+risk and claim no NABARD backing."""
    monkeypatch.setattr(plp, "available", lambda: False)
    c = plp.cite_sector(_sectors()["dairy_buffalo"])
    assert c["available"] is False
    assert c["citations"] == []
    assert "no claim" in c["note"].lower() or "only" in c["note"].lower()


def test_section_retrieval_needs_no_model():
    """The exact path must work without sentence-transformers installed, so the
    slim API image can still cite."""
    hits = plp.by_section(["2.1.6"])
    assert hits and hits[0]["match"] == "section"
