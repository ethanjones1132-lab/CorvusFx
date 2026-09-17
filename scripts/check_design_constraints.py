#!/usr/bin/env python3
"""check_design_constraints.py — pin the APPROVED Corvus Instrument product
design doc that no checker currently references.

SoT: docs/superpowers/specs/2026-08-08-corvus-instrument-design.md
     ("Status: Approved product design", 248 lines).

All existing gate pins target the vertical-slice PLAN; none pin the design
doc the Plan inherits its constraints from. A silent design-doc rewrite
would be the root those Plan pins cannot catch. This checker asserts the
doc retains the architecture-level constraints the whole slice depends on
(read-only, backtick/emphasis-stripped so markdown emphasis cannot fake):

  A1. The doc's Status line still declares "Approved product design".
  A2. The separate-instrument-target boundary sentence (:26).
  A3. The "Existing users and DAW sessions must not be silently migrated
      to the instrument." sentence (:40).
  A4. The "The Corvus effects remain global rather than duplicated per
      voice." sentence (:68).
  A5. The "Per-note sources such as velocity, pressure, note tracking,
      and the modulation envelope may target only per-voice oscillator
      and filter parameters." sentence (:107).
  A6. The first-version exclusion sentences (:89 wavetable/granular/
      sample playback, :109 unlimited routing/audio-rate/scripting).
  A7. The compatibility bullets: preserve the existing FX identifier,
      new instrument identifier, FX and instrument preset namespaces
      stay separate (:164-167).
  A8. The "Licensing and packaging gate" section heading and its
      confirm-ownership-before-commercial-distribution sentence (:172-174).

Anti-drift probes (mutated TEMP COPIES only — the real tree is never
mutated; a no-op mutation aborts the run as a stale-checker alarm):
  N1. drop the never-silently-migrate sentence                          -> FAIL
  N2. drop the global-not-per-voice effects sentence                    -> FAIL
  N3. rewrite the per-note restriction to only cite the envelope        -> FAIL
  N4. drop one of the three compatibility identifier bullets            -> FAIL
  N5. strip the "Licensing and packaging gate" heading                  -> FAIL
Exit 0 only when the real design doc passes every check AND every probe
fires.
"""

import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGN = os.path.join(ROOT, "docs", "superpowers", "specs",
                      "2026-08-08-corvus-instrument-design.md")


def strip_emphasis(text: str) -> str:
    """Neutralize markdown backticks/bold so regexes match plain words."""
    return re.sub(r"`+", "", re.sub(r"\*+", "", text))


def design_checks(text: str):
    """(label, ok, detail) tuples over the comment-strip of the doc."""
    t = strip_emphasis(text)
    res = []
    res.append(("status still Approved product design",
                re.search(r"Status:\s*Approved product design", t)
                is not None, "A1"))
    res.append(("separate instrument target boundary retained",
                re.search(r"preserves\s+Corvus\s+FX\s+and\s+creates\s+a\s+"
                          r"separate\s+instrument\s+target", t) is not None,
                "A2 (:26)"))
    res.append(("never-silently-migrate sentence retained",
                re.search(r"Existing\s+users\s+and\s+DAW\s+sessions\s+must\s+"
                          r"not\s+be\s+silently\s+migrated\s+to\s+the\s+"
                          r"instrument", t) is not None, "A3 (:40)"))
    res.append(("effects stay global, not per voice",
                re.search(r"The\s+Corvus\s+effects\s+remain\s+global\s+"
                          r"rather\s+than\s+duplicated\s+per\s+voice", t)
                is not None, "A4 (:68)"))
    res.append(("per-note sources restricted to per-voice parameters",
                re.search(r"Per-note\s+sources\s+such\s+as\s+velocity,\s+"
                          r"pressure,\s+note\s+tracking,\s+and\s+the\s+"
                          r"modulation\s+envelope\s+may\s+target\s+only\s+"
                          r"per-voice\s+oscillator\s+and\s+filter\s+"
                          r"parameters", t) is not None, "A5 (:107)"))
    res.append(("first-version exclusions (:89) retained",
                re.search(r"The\s+first\s+version\s+does\s+not\s+include\s+"
                          r"wavetable\s+importing", t) is not None,
                "A6a (:89)"))
    res.append(("first-version exclusions (:109) retained",
                re.search(r"The\s+first\s+version\s+does\s+not\s+provide\s+"
                          r"unlimited\s+routing,\s+arbitrary\s+audio-rate\s+"
                          r"modulation,\s+or\s+user\s+scripting", t)
                is not None, "A6b (:109)"))
    res.append(("preserve-existing-FX-identifier bullet retained",
                re.search(r"Preserve\s+the\s+existing\s+Corvus\s+FX\s+"
                          r"plugin\s+identifier", t) is not None,
                "A7a (:164)"))
    res.append(("new-instrument-identifier bullet retained",
                re.search(r"Assign\s+Corvus\s+Instrument\s+a\s+new\s+"
                          r"identifier", t) is not None, "A7b (:165)"))
    res.append(("separate-preset-namespaces bullet retained",
                re.search(r"Keep\s+FX\s+and\s+instrument\s+preset\s+"
                          r"namespaces\s+separate", t) is not None,
                "A7c (:167)"))
    res.append(("licensing and packaging gate section retained",
                re.search(r"Licensing\s+and\s+packaging\s+gate", t)
                is not None, "A8a heading (:172)"))
    res.append(("confirm-ownership-before-commercial sentence retained",
                re.search(r"confirm\s+ownership\s+and\s+contribution\s+"
                          r"history,\s+then\s+choose\s+an\s+explicit\s+"
                          r"licensing\s+boundary", t) is not None,
                "A8b sentence (:174)"))
    return res


def run_text(text: str, verbose=True, tag="design"):
    ok = True
    for label, good, detail in design_checks(text):
        if verbose:
            print(("PASS " if good else "FAIL ") + "%s: %s (%s)"
                  % (tag, label, detail))
        ok = ok and good
    return 0 if ok else 1


def main():
    if not os.path.isfile(DESIGN):
        print("GATE_FAIL: %s missing" % DESIGN)
        return 1
    with open(DESIGN, "r", encoding="utf-8", errors="replace") as f:
        real = f.read()
    if run_text(real) != 0:
        print("GATE_FAIL: design doc drift — see FAIL lines above")
        return 1

    # Negative probes: mutated TEMP COPIES only; no-op mutation = stale alarm.
    negs = [
        ("allow silent migration (drop the :40 sentence)",
         lambda s: s.replace("Existing users and DAW sessions must not be "
                             "silently migrated to the instrument.", "")),
        ("drop the global-not-per-voice sentence (:68)",
         lambda s: s.replace("The Corvus effects remain global rather than "
                             "duplicated per voice.", "")),
        ("narrow the per-note restriction (:107 rewrite)",
         lambda s: s.replace(
             "Per-note sources such as velocity, pressure, note tracking, "
             "and the modulation envelope may target only per-voice "
             "oscillator and filter parameters.",
             "Per-note sources such as the modulation envelope are "
             "restricted by convention.")),
        ("drop the separate-preset-namespaces bullet (:167)",
         lambda s: s.replace("Keep FX and instrument preset namespaces "
                             "separate.", "")),
        ("strip the Licensing and packaging gate heading (:172)",
         lambda s: s.replace("## Licensing and packaging gate",
                             "## Commercial notes")),
    ]
    tmpdir = tempfile.mkdtemp(prefix="check_design_constraints_")
    try:
        for label, mutate in negs:
            mutated = mutate(real)
            if mutated == real:
                print("GATE_FAIL: negative '%s' mutation is a no-op — "
                      "checker stale vs design doc" % label)
                return 1
            if run_text(mutated, verbose=False, tag="neg") == 0:
                print("GATE_FAIL: negative check '%s' did NOT fail — "
                      "checker too weak" % label)
                return 1
            print("PASS neg: rejected -> " + label)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("OK design constraints pinned (approved design doc guarded; "
          "real tree never mutated)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
