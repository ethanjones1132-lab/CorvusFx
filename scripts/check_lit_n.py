"""Scan source/DrippyFX C++ sources for literal backslash-n (lit '\\n') byte pairs
and CRLF line endings — a corruption check left over from a Windows binary-mode
edit. With an argument, checks that single file; with none, checks all sources.
Exits 1 if any literal \\n pair is found (CRLF is reported, not fatal).
"""
import sys
from pathlib import Path

paths = [Path(a) for a in sys.argv[1:]]
if not paths:
    src_dir = Path(__file__).resolve().parent.parent / "source" / "DrippyFX"
    paths = sorted(p for p in src_dir.iterdir() if p.suffix in (".cpp", ".h"))

LIT_N = b"\\" + b"n"
CRLF = b"\r" + b"\n"
bad = []
for p in paths:
    data = p.read_bytes()
    lit = sum(1 for i in range(len(data) - 1) if data[i:i + 2] == LIT_N)
    nl = data.count(b"\n")
    crlf = data.count(CRLF)
    print(f"{p.name}: lit_n={lit} of {nl} lines - CRLF: {crlf}")
    if lit:
        bad.append(p.name)
if bad:
    print(f"FAIL: literal backslash-n pairs (corrupted escape) in: {', '.join(bad)}")
    sys.exit(1)
