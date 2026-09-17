"""Pin the one-shot scripts as historical (ALREADY APPLIED banner).

Two families of one-shot Windows mutation scripts must never be rerun after
their effects are already applied in the current SoT:

1. source/DrippyFX/scripts/ — 5 migration scripts targeting the Windows build
   tree (CRLF paths), effects already applied, kept in-tree as a record.
2. scripts/ (repo-root one-shots) — fix_chorus_rate_cache.py and
   fix_reverb_modphase_cache.py are the same hazard class: they read/write
   SRC = "C:/Projects/Corvus VST/..." in write mode (open rb -> str.replace ->
   write back) against already-applied migrations, but historically lived
   OUTSIDE the checker's jurisdiction.

Each script must always carry an "ALREADY APPLIED — DO NOT RERUN" banner so a
future agent never reruns it.
"""
import pathlib
import re
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
PLUGIN_SCRIPTS_DIR = ROOT / "source" / "DrippyFX" / "scripts"
ROOT_SCRIPTS_DIR = ROOT / "scripts"
HISTORICAL = [
    "fix_destructor.py",
    "fix_juce8_params.py",
    "fix_levelmeters_access.py",
    "fix_master_mono_oversample.py",
    "update_roadmap.py",
]
# Repo-root one-shot performance-capture scripts: same Windows-tree write-mode
# hazard class as the five above, but living under scripts/ itself.
ROOT_HISTORICAL = [
    "fix_chorus_rate_cache.py",
    "fix_reverb_modphase_cache.py",
]
BANNER = re.compile(r"ALREADY APPLIED[^\n]*DO NOT RERUN", re.IGNORECASE)

NO_BANNER_BODY = (
    '"""docstring"""\n'
    "import sys\n"
)
WITH_BANNER_BODY = (
    '"""fix: benign probe\n'
    "\n"
    "ALREADY APPLIED — DO NOT RERUN (migration shipped in an earlier commit).\n"
    '"""\n'
    "import sys\n"
)


def _banner_errors(base_dir: pathlib.Path, names) -> list[str]:
    """The real assertion path. Reusable on any directory (temp copies too)."""
    errors = []
    for name in names:
        path = base_dir / name
        if not path.exists():
            errors.append(f"missing: {path} — historical one-shots must stay in-tree")
            continue
        if not BANNER.search(path.read_text(encoding="utf-8", errors="replace")[:2000]):
            errors.append(f"{name}: no 'ALREADY APPLIED — DO NOT RERUN' banner in its header")
    return errors


def _probe_duplicate_historical_rejected():
    """Same file name under BOTH lists: the assertion loop must not dedupe them
    (a name checked only once would let the second list's copy silently skip)."""
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td) / "scripts"
        base.mkdir()
        (base / ROOT_HISTORICAL[0]).write_text(NO_BANNER_BODY, encoding="utf-8")
        if not _banner_errors(base, [ROOT_HISTORICAL[0]]):
            print("PROBE_FAIL: banner-missing temp copy was NOT rejected — checker asserting nothing")
            return False
    return True


def _probe_noop_guard():
    """A copy WITH the banner must pass — guards against over-strict stale alarms."""
    with tempfile.TemporaryDirectory() as td:
        base = pathlib.Path(td) / "scripts"
        base.mkdir()
        (base / ROOT_HISTORICAL[0]).write_text(WITH_BANNER_BODY, encoding="utf-8")
        if _banner_errors(base, [ROOT_HISTORICAL[0]]):
            print("PROBE_FAIL: banner-bearing temp copy wrongly rejected — checker over-strict")
            return False
    return True


def main() -> int:
    errors: list[str] = []
    errors += _banner_errors(PLUGIN_SCRIPTS_DIR, HISTORICAL)
    errors += _banner_errors(ROOT_SCRIPTS_DIR, ROOT_HISTORICAL)

    # Probes run on TEMP COPIES in a temp dir; the real tree is never mutated.
    if not _probe_duplicate_historical_rejected():
        errors.append("self-probe: banner-missing rejection machinery broken")
    if not _probe_noop_guard():
        errors.append("self-probe: noop guard broken (banner copy must pass)")

    if errors:
        for e in errors:
            print("FAIL:", e)
        return 1
    print(
        f"OK: all {len(HISTORICAL)} migration scripts under source/DrippyFX/scripts/ "
        f"and all {len(ROOT_HISTORICAL)} one-shot capture scripts under scripts/ "
        "carry the 'ALREADY APPLIED — DO NOT RERUN' banner"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
