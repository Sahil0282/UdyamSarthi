#!/usr/bin/env python3
"""Checks 4 and 5 — drive the real UI in a real browser.

Asserts against the live MapLibre instance (which layers and sources exist,
what geometry they hold) rather than against a screenshot, so a blank map
cannot pass. Screenshots are saved alongside as evidence for a human.
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8000/"
OUT = Path("/tmp/ui")
OUT.mkdir(exist_ok=True)
fails: list[str] = []


def check(cond, label, detail=""):
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"  — {detail}" if detail else ""))
    if not cond:
        fails.append(label)


def run_case(page, village, capital, expect_verdict, tag):
    print(f"\n=== {village} (capital {capital:,}) ===")
    page.goto(BASE, wait_until="load")
    page.wait_for_selector("#map", timeout=30000)
    page.wait_for_selector(".verdict", timeout=90000)   # initial auto-run
    # The query form collapses to a summary row once a result exists, so it has
    # to be reopened before the inputs are reachable.
    if not page.query_selector_all("input"):
        page.click(".qsum")
        page.wait_for_selector("input", timeout=10000)
    inputs = page.query_selector_all("input")
    inputs[0].fill(village)
    page.fill("input[type=number]", str(capital))
    page.click("button:has-text('Get advice')")
    page.wait_for_function(
        "() => document.querySelector('.vtitle') && "
        "!document.querySelector('button[disabled]')", timeout=90000)
    page.wait_for_timeout(3000)

    verdict = page.inner_text(".vtitle").strip()
    check(verdict.replace(" ", "_") == expect_verdict, f"verdict is {expect_verdict}",
          f"got {verdict!r}")

    # --- the map really drew the layers ---
    layers = page.evaluate("""() => {
        const m = window.__map; if (!m) return null;
        return ['vil-f','vil-l','ring-f','ring-l','pts']
                 .filter(id => !!m.getLayer(id));
    }""")
    check(layers is not None and {"vil-f", "ring-f", "ring-l"} <= set(layers or []),
          "map has village polygon + 8km ring layers", str(layers))

    geom = page.evaluate("""() => {
        const m = window.__map; if (!m) return null;
        const v = m.getSource('vil')._data.geometry;
        const r = m.getSource('ring')._data.geometry;
        const pts = m.getSource('pts')._data.features.length;
        const ringArea = (g)=>{const c=g.coordinates[0];
          let x0=180,y0=90,x1=-180,y1=-90;
          c.forEach(p=>{x0=Math.min(x0,p[0]);y0=Math.min(y0,p[1]);
                        x1=Math.max(x1,p[0]);y1=Math.max(y1,p[1]);});
          return {w:(x1-x0), h:(y1-y0), cx:(x0+x1)/2, cy:(y0+y1)/2};};
        return {vil:ringArea(v), ring:ringArea(r), points:pts,
                vtype:v.type, rtype:r.type};
    }""")
    if geom:
        check(geom["vtype"] == "Polygon" and geom["rtype"] == "Polygon",
              "both geometries are polygons")
        check(geom["ring"]["w"] > geom["vil"]["w"],
              "ring is larger than the village polygon",
              f"ring {geom['ring']['w']:.3f}deg vs village {geom['vil']['w']:.3f}deg")
        check(73.0 < geom["vil"]["cx"] < 76.0 and 18.0 < geom["vil"]["cy"] < 20.5,
              "village sits inside Ahmadnagar's bounds",
              f"centroid ({geom['vil']['cx']:.3f}, {geom['vil']['cy']:.3f})")
        print(f"      procurement points plotted: {geom['points']}")

    # --- every number tappable, showing provenance ---
    nums = page.query_selector_all(".num")
    check(len(nums) >= 15, "numbers are tappable", f"{len(nums)} tappable numbers")
    nums[0].click()
    page.wait_for_selector(".prov", timeout=5000)
    prov = page.inner_text(".prov")
    check("confidence" in prov and "level" in prov,
          "tapping a number reveals source/year/geo_level/confidence",
          prov.replace("\n", " | ")[:110])

    # A Fact known to be state-level with a long note. Each tap inserts its own
    # .prov panel inline, so read every open panel rather than just the first.
    found = False
    for n in page.query_selector_all(".num"):
        if "62.18" in (n.inner_text() or ""):
            n.click(); page.wait_for_timeout(500)
            texts = [el.inner_text() for el in page.query_selector_all(".prov")]
            hit = next((t for t in texts if "Kolhapur" in t), "")
            found = bool(hit) and "state level" in hit
            check(found, "milk price shows the Kolhapur proxy note in the UI",
                  hit.replace("\n", " | ")[:120])
            break
    if not found:
        check(False, "milk price row found in the UI",
              "no .num element contained 62.18")

    body = page.inner_text("body")
    check("LOW" in body or "low" in body, "confidence is visible in the UI")

    page.screenshot(path=str(OUT / f"{tag}.png"), full_page=False)
    print(f"      screenshot: {OUT / f'{tag}.png'}")
    return page


def main() -> int:
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        page = b.new_page(viewport={"width": 1440, "height": 950})
        # The app assigns window.__map itself; no instrumentation needed.
        run_case(page, "nimgaon jali", 100000, "PROCEED", "nimgaon_jali")
        run_case(page, "murmi", 25000, "RECONSIDER", "murmi")

        # override button on the refusal case
        print("\n=== override on murmi ===")
        btn = page.query_selector("button:has-text('I still want')")
        check(btn is not None, "override button offered on RECONSIDER")
        if btn:
            btn.scroll_into_view_if_needed()
            btn.click()
            page.wait_for_function(
                "() => document.body.innerText.includes('Override applied')",
                timeout=90000)
            page.wait_for_timeout(500)
            body = page.inner_text("body")
            check("Override applied" in body, "override honoured in UI")
            check("RECONSIDER" in page.inner_text(".vtitle"),
                  "verdict NOT softened by override")
            check("risk mitigation" in body.lower(), "mitigation guidance shown")
            page.screenshot(path=str(OUT / "murmi_override.png"))
            print(f"      screenshot: {OUT / 'murmi_override.png'}")
        b.close()

    print(f"\n{'ALL UI CHECKS PASSED' if not fails else 'FAILURES: ' + ', '.join(fails)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
