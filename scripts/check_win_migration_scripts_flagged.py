"""Pin the Windows one-shot migration scripts as historical (ALREADY APPLIED banner).

source/DrippyFX/scripts/ holds 5 one-shot migration scripts that target the
Windows build tree (CRLF paths). All five effects are already applied in the
current SoT — the scripts are kept in-tree as a record of the migration, and
each must carry an "ALREADY APPLIED — DO NOT RERUN" banner so a future agent
never reruns them after their effects are applied.
"""
import pathlib
import re
import sys

SCRIPTS_DIR = pathlib.Path(__file__).resolve().parent.parent / "source" / "DrippyFX" / "scripts"
HISTORICAL = [
    "fix_destructor.py",
    "fix_juce8_params.py",
    "fix_levelmeters_access.py",
    "fix_master_mono_oversample.py",
    "update_roadmap.py",
]
BANNER = re.compile(r"ALREADY APPLIED[^\n]*DO NOT RERUN", re.IGNORECASE)


def main() -> int:
    errors: list[str] = []
    for name in HISTORICAL:
        path = SCRIPTS_DIR / name
        if not path.exists():
            errors.append(f"missing: {path} — the 5 migration scripts must stay in-tree")
            continue
        if not BANNER.search(path.read_text(encoding="utf-8", errors="replace")[:2000]):
            errors.append(f"{name}: no 'ALREADY APPLIED — DO NOT RERUN' banner in its header")
    if errors:
        for e in errors:
            print("FAIL:", e)
        return 1
    print(f"OK: all {len(HISTORICAL)} Windows one-shot migration scripts carry the 'ALREADY APPLIED — DO NOT RERUN' banner")
    return 0


if __name__ == "__main__":
    sys.exit(main())
