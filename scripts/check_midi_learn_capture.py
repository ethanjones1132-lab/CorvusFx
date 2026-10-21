#!/usr/bin/env python3
"""Headless checker: MIDI-learn capture invariants + the CC snapshot shape.

Two VALID snapshot representations of the processBlock CC apply path are
accepted; everything else must fail:

  (1) "local-map" (current master) — a local snapshot map declared in
      processBlock, copied under the lock:

          std::map<int, juce::String> mapSnapshot;
          {
              const juce::ScopedLock lock(midiMapLock);
              ... capture writes midiMap[cc] under the lock ...
              mapSnapshot = midiMap;
          }
          ... mapSnapshot.find(cc) ... setValueNotifyingHost ...

  (2) "member-vector" (the CV-017 prerequisite shape) — a processor member
      vector whose capacity is established OFF the audio thread, refilled
      under the same lock with a bounded append, and scanned after release:

          header:  std::vector<std::pair<int, juce::String>> mapSnapshot;
          ctor:    mapSnapshot.reserve(128);
          prepare: mapSnapshot.reserve(128);
          {
              const juce::ScopedLock lock(midiMapLock);
              ... capture writes midiMap[cc] under the lock ...
              mapSnapshot.clear();
              for (const auto& [cc, pid] : midiMap)
                  if (cc >= 0 && cc <= 127)
                      mapSnapshot.emplace_back(cc, pid);
          }
          for (const auto& mapping : mapSnapshot)
              if (mapping.first == cc) ... getParameter(mapping.second) ...
                      -> setValueNotifyingHost(...)

Common assertions (both shapes, unchanged from the original gate):
  (a) the capture branch still clears midiLearnActive after capturing,
  (b) the midiMap write for the captured CC happens inside the SAME held
      midiMapLock block,
  (c) no setValueNotifyingHost inside the lock (capture must not jump the
      host value; host latency must not sit in the critical section),
  (d) capture REFUSES to overwrite a CC already mapped to a different
      parameter (existing-lookup + different-param refusal in the branch).

Member-vector-only assertions (vacuous for the local-map shape):
  (e) the header declares the processor member vector (a local/shadowed
      copy is rejected — it reallocates on the audio thread),
  (f) the constructor AND prepareToPlay reserve at least 128 entries
      (the full 0..127 CC domain; keys are unique so 128 bounded appends
      can never outgrow the reservation). reserve(1), reserve(127), a
      non-literal capacity and a missing reserve all fail,
  (g) no reserve/push_back/resize/insert/assign/emplace on mapSnapshot
      anywhere in processBlock (capacity is off-thread only),
  (h) the refill clears the vector under the lock, then iterates midiMap
      and appends only entries guarded by 0 <= cc <= 127 — a bounded
      refill of at most the reserved capacity,
  (i) the post-lock apply path scans the vector for entry.first == cc and
      notifies the host through that entry's parameter id (mapping->second).

Self-tests (all in memory — the real C++ tree is never written):
  * positive fixtures for BOTH shapes, including the member header;
  * negative fixture mutations: reserve(1), absent capacity guard, reserve
    inside processBlock, capture write outside the lock, host notification
    under the lock, lost flag clear, lost refuse-to-steal;
  * a stale/no-op probe self-test proving no-op mutations are still caught;
  * a multi-lock member-vector fixture proving the audio-thread mutations
    anchor on the processBlock refill, not the first midiMapLock in the file;
  * shape-aware probes against the live tree: every probe applicable to the
    DETECTED shape must hit a live pattern and be rejected (a probe whose
    pattern vanished is reported as NO-OP and fails the run, so the probes
    can never silently go stale), and probes for the other representation
    are not run at all.

Exit 0 = ok, 1 = violation with line-cited diagnostics.
"""
import re
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "source" / "DrippyFX"
CPP = SRC / "PluginProcessor.cpp"
HDR = SRC / "PluginProcessor.h"

# Full legal MIDI CC domain: 0..127. midiMap keys are unique, so a refill
# guarded to that domain appends at most 128 entries.
MIN_CAPACITY = 128


class Reject(Exception):
    """Structural violation detected in a (real or fixture) source text."""


class StaleProbe(Exception):
    """A self-probe pattern no longer matches text it claims to target."""


def fail(msg) -> NoReturn:
    print(f"MIDI-LEARN-CAPTURE FAIL: {msg}")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def block_at(text, pos):
    """Brace-matched (start, end, block) for the first '{' at/after pos."""
    lb = text.find("{", pos)
    if lb == -1:
        return None
    depth = 0
    for k in range(lb, len(text)):
        if text[k] == "{":
            depth += 1
        elif text[k] == "}":
            depth -= 1
            if depth == 0:
                return lb, k + 1, text[lb:k + 1]
    return None


def enclosing_block(text, pos):
    start = text.rfind("{", 0, pos)
    while start != -1:
        found = block_at(text, start)
        if found and found[0] <= pos < found[1]:
            return found
        start = text.rfind("{", 0, start)
    return None


def method_body(code, signature):
    """Body of `CorvusFXAudioProcessor::<signature>` (brace-matched)."""
    m = re.search(r"\bCorvusFXAudioProcessor::" + signature + r"\s*\(", code)
    if not m:
        return None
    found = block_at(code, m.end())
    return found[2] if found else None


def class_body(header):
    m = re.search(r"\bclass\s+CorvusFXAudioProcessor\b", header)
    if not m:
        return None
    found = block_at(header, m.end())
    return found[2] if found else None


MEMBER_VEC_RE = re.compile(
    r"std::vector\s*<\s*std::pair\s*<\s*int\s*,\s*juce::String\s*>\s*>\s*"
    r"mapSnapshot\s*(?:\{\s*\})?\s*;")
LOCAL_MAP_RE = re.compile(
    r"std::map\s*<\s*int\s*,\s*juce::String\s*>\s*mapSnapshot\s*;")
LOCAL_VEC_RE = re.compile(
    r"std::vector\s*<[^;{}]*>\s*mapSnapshot\s*;")
RESERVE_RE = re.compile(r"mapSnapshot\s*\.\s*reserve\s*\(\s*([0-9]+)\s*\)")
GROWTH_RE = re.compile(
    r"mapSnapshot\s*\.\s*(push_back|resize|insert|assign|emplace)\s*\(")


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------
def _capacity(body, where):
    """Sufficient off-thread reserve() capacity, or Reject."""
    if body is None:
        raise Reject(
            f"could not locate the {where} body — the off-thread mapSnapshot "
            f"capacity cannot be verified")
    caps = [int(x) for x in RESERVE_RE.findall(body)]
    if not caps:
        raise Reject(
            f"{where} no longer reserves mapSnapshot capacity — the member "
            f"vector reallocates on the audio thread at the first refill")
    low = min(caps)
    if low < MIN_CAPACITY:
        raise Reject(
            f"{where} reserves only {low} mapSnapshot "
            f"entr{'y' if low == 1 else 'ies'} — at least {MIN_CAPACITY} are "
            f"required (the full 0..127 CC domain; keys are unique, so a "
            f"bounded refill can never grow past the reservation)")
    return low


def _check_local_map(body, lock, apply_region):
    """Shape (1): local std::map snapshot copied under the lock."""
    _, (lock_start, _, lock_block) = lock

    decl = LOCAL_MAP_RE.search(body)
    if not decl or decl.start() > lock_start:
        raise Reject(
            "processBlock midiMap snapshot declaration missing or no longer "
            "precedes the midiMapLock block")
    if not re.search(r"mapSnapshot\s*=\s*midiMap\s*;", lock_block):
        raise Reject(
            "the lock block no longer copies midiMap into mapSnapshot — the "
            "apply path would read a stale snapshot or copy outside the lock")
    if re.search(r"\bmidiMap\b", apply_region):
        raise Reject(
            "the apply path dereferences the live midiMap after midiMapLock "
            "is released — it must read only the snapshot copy")
    find_m = re.search(r"mapSnapshot\s*\.\s*find\s*\(\s*cc\s*\)", apply_region)
    if not find_m:
        raise Reject("the apply path no longer looks up the CC in mapSnapshot")
    notify = re.search(r"setValueNotifyingHost", apply_region)
    if not notify or notify.start() < find_m.start():
        raise Reject(
            "the apply path does not notify the host from the snapshot lookup")
    if not re.search(
            r"getParameter\s*\(\s*\w+\s*(?:->|\.)\s*second\s*\)", apply_region):
        raise Reject(
            "the apply path no longer resolves the mapped parameter id from "
            "the snapshot entry")


def _check_member_vector(code, body, header, lock, apply_region):
    """Shape (2): preallocated processor member vector, bounded refill."""
    _, (_, _, lock_block) = lock

    if MEMBER_VEC_RE.search(class_body(header) or "") is None:
        raise Reject(
            "the plugin header does not declare the preallocated processor "
            "member `std::vector<std::pair<int, juce::String>> mapSnapshot;`")

    # (g) no capacity work on the audio thread
    if RESERVE_RE.search(body):
        raise Reject(
            "mapSnapshot.reserve(...) runs inside processBlock — capacity must "
            "be established off the audio thread (constructor + prepareToPlay)")
    growth = GROWTH_RE.search(body)
    if growth:
        raise Reject(
            f"mapSnapshot.{growth.group(1)}(...) runs inside processBlock — "
            f"the refill must be a bounded emplace_back of at most one entry "
            f"per legal CC")

    # (f) sufficient off-thread capacity in BOTH off-thread hooks
    ctor_cap = _capacity(method_body(code, "CorvusFXAudioProcessor"),
                         "the constructor")
    prep_cap = _capacity(method_body(code, "prepareToPlay"), "prepareToPlay")

    # (h) clear + guarded, bounded refill under the same lock
    clear_m = re.search(r"mapSnapshot\s*\.\s*clear\s*\(\s*\)", lock_block)
    if not clear_m:
        raise Reject(
            "the lock block no longer clears mapSnapshot before the refill — "
            "entries accumulate every block and the vector outgrows its "
            "reserved capacity")
    refill = re.search(
        r"mapSnapshot\s*\.\s*emplace_back\s*\(([^)]*)\)", lock_block)
    if not refill:
        raise Reject(
            "the lock block no longer refills mapSnapshot from midiMap")
    if len(re.findall(r"mapSnapshot\s*\.\s*emplace_back\s*\(", lock_block)) != 1:
        raise Reject(
            "the lock block appends to mapSnapshot more than once — the "
            "refill must append exactly one bounded entry per midiMap row")
    if refill.start() < clear_m.start():
        raise Reject(
            "the mapSnapshot refill runs before the clear — stale entries "
            "from the previous block are appended to the snapshot")

    loop = None
    for m in re.finditer(r"for\s*\(([^)]*)\)", lock_block[:refill.start()]):
        if re.search(r":\s*midiMap\s*$", m.group(1).strip()):
            loop = m
            break
    if loop is None:
        raise Reject(
            "the mapSnapshot refill is not bounded by iterating midiMap")
    destr = re.search(r"\[\s*(\w+)\s*,\s*(\w+)\s*\]", loop.group(1))
    if not destr:
        raise Reject(
            "the refill loop does not destructure [cc, pid] from midiMap")
    cc_name, pid_name = destr.group(1), destr.group(2)
    args = [a.strip() for a in refill.group(1).split(",")]
    if args[:2] != [cc_name, pid_name]:
        raise Reject(
            f"the refill appends {args!r} instead of the loop's "
            f"({cc_name}, {pid_name}) pair")

    guard = None
    for g in re.finditer(r"if\s*\(([^)]*)\)",
                         lock_block[loop.end():refill.start()]):
        cond = re.sub(r"\s+", " ", g.group(1)).strip()
        if (re.fullmatch(rf"{re.escape(cc_name)} >= 0 && "
                         rf"{re.escape(cc_name)} <= 127", cond)
                or re.fullmatch(rf"{re.escape(cc_name)} >= 0 && "
                                rf"{re.escape(cc_name)} < 128", cond)):
            guard = g
            break
    if guard is None:
        raise Reject(
            f"the refill append is not guarded by the legal CC range "
            f"(0 <= {cc_name} <= 127) — an out-of-range key can grow the "
            f"vector past its off-thread capacity")
    # Both accepted guards admit exactly 128 distinct keys, and both
    # off-thread reserves hold at least 128 => refill <= capacity.
    if min(ctor_cap, prep_cap) < 128:
        raise Reject(
            "the off-thread mapSnapshot capacity is smaller than the refill "
            "domain — a full legal CC map would reallocate on the audio thread")

    # (i) post-lock apply path scans the vector and notifies via .second
    applied = False
    for m in re.finditer(
            r"for\s*\(\s*(?:const\s+)?auto\s*(?:&&|&|\*)?\s*(\w+)\s*:\s*"
            r"mapSnapshot\s*\)", apply_region):
        var = re.escape(m.group(1))
        seg = apply_region[m.end():m.end() + 2000]
        notify = re.search(r"setValueNotifyingHost", seg)
        if not notify:
            continue
        seg = seg[:notify.end()]
        if not re.search(rf"\b{var}\s*(?:->|\.)\s*first\s*==\s*cc", seg):
            continue
        if not re.search(rf"getParameter\s*\(\s*{var}\s*(?:->|\.)\s*second\s*\)",
                         seg):
            continue
        applied = True
        break
    if not applied:
        raise Reject(
            "the post-lock apply path does not scan mapSnapshot for "
            "entry.first == cc and notify the host through that entry's "
            "parameter id (mapping->second)")
    if re.search(r"mapSnapshot\s*\.\s*emplace_back\s*\(", apply_region):
        raise Reject(
            "the post-lock apply path appends to mapSnapshot — the snapshot "
            "is refilled under the lock only; post-lock growth reallocates "
            "once the reserved capacity is exhausted")
    if re.search(r"\bmidiMap\b", apply_region):
        raise Reject(
            "the apply path still dereferences the live midiMap after "
            "midiMapLock is released — it must read only the preallocated "
            "snapshot")


def check(raw_cpp, raw_header):
    """Gate one cpp/header pair. Returns the detected shape or raises Reject."""
    code = strip_comments(raw_cpp)
    header = strip_comments(raw_header)

    body = method_body(code, "processBlock")
    if body is None:
        raise Reject("could not locate the PluginProcessor::processBlock body")

    # ---- locate the audio-thread CC capture/snapshot critical section ----
    lock = None
    for cand in re.finditer(
            r"ScopedLock\s+lock\s*\(\s*midiMapLock\s*\)", body):
        enc = enclosing_block(body, cand.start())
        if enc and "midiLearnActive" in enc[2] and re.search(
                r"midiMap\s*\[", enc[2]):
            lock = (cand, enc)
            break
    if lock is None:
        raise Reject(
            "capture block no longer acquires midiMapLock under the snapshot "
            "— capture/snapshot locking discipline lost")
    lock_start, lock_end, lock_block = lock[1]

    parent = enclosing_block(body, lock_start)
    apply_region = body[lock_end:parent[1]] if parent else body[lock_end:]

    # ---- common assertions (both shapes) ---------------------------------
    if "midiMap[cc] = midiLearnParamID" not in lock_block:
        raise Reject(
            "capture branch does not write midiMap under the held midiMapLock "
            "— the write must stay inside the lock block")
    if "midiLearnActive = false" not in lock_block:
        raise Reject(
            "capture branch no longer clears midiLearnActive after capture")
    if "setValueNotifyingHost" in lock_block:
        raise Reject(
            "capture branch calls setValueNotifyingHost — capture must not "
            "jump the host value (and host notification must never run while "
            "midiMapLock is held)")
    if "midiMap.find(cc)" not in lock_block:
        raise Reject(
            "capture branch does not look up the pre-existing midiMap entry "
            "for the CC — overwriting an already-mapped CC silently steals it "
            "from the other parameter")
    if "existing->second != midiLearnParamID" not in lock_block:
        raise Reject(
            "capture branch does not refuse a CC already mapped to a "
            "DIFFERENT parameter (expected the "
            "existing->second != midiLearnParamID guard)")

    # ---- identify the snapshot representation ----------------------------
    has_member = MEMBER_VEC_RE.search(class_body(header) or "")
    has_local_map = LOCAL_MAP_RE.search(body)
    has_local_vec = LOCAL_VEC_RE.search(body)

    if has_local_vec:
        raise Reject(
            "processBlock declares a LOCAL mapSnapshot vector — every block "
            "then allocates on the audio thread; mapSnapshot must be the "
            "preallocated processor member")
    if has_member and has_local_map:
        raise Reject(
            "mapSnapshot is declared BOTH as the preallocated processor "
            "member and as a LOCAL std::map in processBlock — the local "
            "shadows the member, so the audio-thread path allocates a fresh "
            "map every block")

    if has_member:
        _check_member_vector(code, body, header, lock, apply_region)
        return "member-vector"
    if has_local_map:
        _check_local_map(body, lock, apply_region)
        return "local-map"
    raise Reject(
        "no recognisable mapSnapshot snapshot representation — expected "
        "either the local `std::map<int, juce::String> mapSnapshot` shape or "
        "the preallocated header-member vector shape")


# ---------------------------------------------------------------------------
# In-memory positive fixtures (one per accepted representation)
# ---------------------------------------------------------------------------
FIXTURE_OLD_HEADER = """#pragma once
class CorvusFXAudioProcessor : public juce::AudioProcessor
{
public:
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&);
private:
    std::map<int, juce::String> midiMap;
    juce::CriticalSection midiMapLock;
    std::atomic<bool> midiLearnActive{false};
    juce::String midiLearnParamID;
};
"""

FIXTURE_NEW_HEADER = """#pragma once
class CorvusFXAudioProcessor : public juce::AudioProcessor
{
public:
    void processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer&);
private:
    std::map<int, juce::String> midiMap;
    juce::CriticalSection midiMapLock;
    std::vector<std::pair<int, juce::String>> mapSnapshot;
    std::atomic<bool> midiLearnActive{false};
    juce::String midiLearnParamID;
};
"""

_CAPTURE = """            if (midiLearnActive)
            {
                for (const auto& metadata : midiMessages)
                {
                    auto msg = metadata.getMessage();
                    if (msg.isController() && capturedCc == -1)
                    {
                        const int cc = msg.getControllerNumber();
                        auto existing = midiMap.find(cc);
                        if (existing != midiMap.end() && existing->second != midiLearnParamID)
                            continue;
                        capturedCc = cc;
                        midiMap[cc] = midiLearnParamID;
                        midiLearnActive = false;
                    }
                }
            }
"""

FIXTURE_OLD_CPP = """void CorvusFXAudioProcessor::CorvusFXAudioProcessor() {}

void CorvusFXAudioProcessor::prepareToPlay(double, int) {}

void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer& midiMessages)
{
    if (!midiMessages.isEmpty())
    {
        std::map<int, juce::String> mapSnapshot;
        int capturedCc = -1;
        {
            const juce::ScopedLock lock(midiMapLock);
""" + _CAPTURE + """            mapSnapshot = midiMap;
        }
        for (const auto& metadata : midiMessages)
        {
            auto msg = metadata.getMessage();
            if (!msg.isController())
                continue;
            int cc = msg.getControllerNumber();
            if (cc == capturedCc)
                continue;
            const float normValue = msg.getControllerValue() / 127.0f;
            auto it = mapSnapshot.find(cc);
            if (it != mapSnapshot.end())
            {
                auto* p = apvts.getParameter(it->second);
                if (p) p->setValueNotifyingHost(normValue);
            }
        }
    }
}
"""

FIXTURE_NEW_CPP = """CorvusFXAudioProcessor::CorvusFXAudioProcessor()
{
    mapSnapshot.reserve(128);
}

void CorvusFXAudioProcessor::prepareToPlay(double, int)
{
    mapSnapshot.reserve(128);
}

void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer& midiMessages)
{
    if (!midiMessages.isEmpty())
    {
        int capturedCc = -1;
        {
            const juce::ScopedLock lock(midiMapLock);
""" + _CAPTURE + """            mapSnapshot.clear();
            for (const auto& [cc, pid] : midiMap)
                if (cc >= 0 && cc <= 127)
                    mapSnapshot.emplace_back(cc, pid);
        }
        for (const auto& metadata : midiMessages)
        {
            auto msg = metadata.getMessage();
            if (!msg.isController())
                continue;
            int cc = msg.getControllerNumber();
            if (cc == capturedCc)
                continue;
            const float normValue = msg.getControllerValue() / 127.0f;
            for (const auto& mapping : mapSnapshot)
                if (mapping.first == cc)
                {
                    auto* p = apvts.getParameter(mapping.second);
                    if (p) p->setValueNotifyingHost(normValue);
                }
        }
    }
}
"""

# The unmerged CV-017 processor edits midiMap from the message thread under an
# earlier ScopedLock on the same lock; processBlock's own lock comes later.
# Audio-thread probes must anchor on the processBlock refill clear, never on
# the first midiMapLock in the translation unit.
FIXTURE_NEW_MULTILOCK_CPP = """CorvusFXAudioProcessor::CorvusFXAudioProcessor()
{
    mapSnapshot.reserve(128);
}

void CorvusFXAudioProcessor::prepareToPlay(double, int)
{
    mapSnapshot.reserve(128);
}

void CorvusFXAudioProcessor::setMidiMapFromMessageThread(int cc, const juce::String& pid)
{
    const juce::ScopedLock lock(midiMapLock);
    midiMap[cc] = pid;
}

void CorvusFXAudioProcessor::processBlock(juce::AudioBuffer<float>&, juce::MidiBuffer& midiMessages)
{
    if (!midiMessages.isEmpty())
    {
        int capturedCc = -1;
        {
            const juce::ScopedLock lock(midiMapLock);
""" + _CAPTURE + """            mapSnapshot.clear();
            for (const auto& [cc, pid] : midiMap)
                if (cc >= 0 && cc <= 127)
                    mapSnapshot.emplace_back(cc, pid);
        }
        for (const auto& metadata : midiMessages)
        {
            auto msg = metadata.getMessage();
            if (!msg.isController())
                continue;
            int cc = msg.getControllerNumber();
            if (cc == capturedCc)
                continue;
            const float normValue = msg.getControllerValue() / 127.0f;
            for (const auto& mapping : mapSnapshot)
                if (mapping.first == cc)
                {
                    auto* p = apvts.getParameter(mapping.second);
                    if (p) p->setValueNotifyingHost(normValue);
                }
        }
    }
}
"""

# `mapSnapshot.clear();` is the processBlock refill: the earlier message-thread
# locks do not carry it. Mutating the first ScopedLock in the file would leave
# processBlock untouched, so check() would still accept a member-vector tree.
REFILL_CLEAR = r"(mapSnapshot\s*\.\s*clear\s*\(\s*\)\s*;)"
RESERVE_AT_REFILL = (REFILL_CLEAR, r"mapSnapshot.reserve(128);\n \1")
SHADOW_AT_REFILL = (
    REFILL_CLEAR,
    r"std::vector<std::pair<int, juce::String>> mapSnapshot;\n \1")

# The old (broken) anchor — the first midiMapLock in the translation unit.
# Kept only for the multi-lock fixture guard below, which proves it reaches the
# message-thread lock instead of processBlock and is therefore not sufficient.
OLD_FIRST_LOCK_ANCHOR = (
    r"((?:const\s+)?juce::ScopedLock\s+lock\s*\(\s*midiMapLock\s*\)\s*;)")


# ---------------------------------------------------------------------------
# Mutation plumbing (in memory only; StaleProbe keeps no-op detection alive)
# ---------------------------------------------------------------------------
def mutate(text, pattern, repl, label):
    out, n = re.subn(pattern, repl, text, count=1)
    if n == 0 or out == text:
        raise StaleProbe(label)
    return out


def expect_ok(label, cpp, hdr, expected_shape):
    try:
        got = check(cpp, hdr)
    except Reject as exc:
        fail(f"positive fixture '{label}' was REJECTED: {exc}")
    if got != expected_shape:
        fail(f"positive fixture '{label}' detected as '{got}', expected "
             f"'{expected_shape}'")
    print(f"midi-learn-capture fixture '{label}': accepted as {got}")


def expect_fixture_reject(label, cpp, hdr, why):
    try:
        check(cpp, hdr)
    except Reject as exc:
        print(f"midi-learn-capture fixture mutation '{label}': rejected as "
              f"expected ({exc})")
        return
    fail(f"fixture mutation '{label}' was NOT rejected — {why}")


def fixture_mutation(label, cpp_mutations=(), hdr_mutations=(),
                     cpp=FIXTURE_NEW_CPP, hdr=FIXTURE_NEW_HEADER):
    new_cpp, new_hdr = cpp, hdr
    try:
        for pattern, repl in cpp_mutations:
            new_cpp = mutate(new_cpp, pattern, repl, label)
        for pattern, repl in hdr_mutations:
            new_hdr = mutate(new_hdr, pattern, repl, label)
    except StaleProbe:
        fail(f"fixture mutation '{label}': NO-OP MUTATION (pattern absent) — "
             f"the negative fixture is stale")
    return new_cpp, new_hdr


# ---------------------------------------------------------------------------
# Real tree
# ---------------------------------------------------------------------------
for required in (CPP, HDR):
    if not required.exists():
        fail(f"missing source file {required}")

# Windows: the source carries UTF-8 punctuation in comments, so every read
# decodes explicitly as UTF-8 (the locale default fails on those bytes).
cpp_text = CPP.read_text(encoding="utf-8")
hdr_text = HDR.read_text(encoding="utf-8")

try:
    shape = check(cpp_text, hdr_text)
except Reject as exc:
    fail(str(exc))

print(f"midi-learn-capture: capture clears the flag, writes midiMap inside "
      f"the lock, no host jump, and refuses to overwrite a foreign CC mapping")
print(f"midi-learn-capture: snapshot shape '{shape}' accepted")
print("midi-learn-capture: real tree OK")


# ---------------------------------------------------------------------------
# Shape-aware negative self-probes against the LIVE tree (in-memory copies)
# ---------------------------------------------------------------------------
def live_probe(label, why, cpp_mutations=(), hdr_mutations=()):
    new_cpp, new_hdr = cpp_text, hdr_text
    try:
        for pattern, repl in cpp_mutations:
            new_cpp = mutate(new_cpp, pattern, repl, label)
        for pattern, repl in hdr_mutations:
            new_hdr = mutate(new_hdr, pattern, repl, label)
    except StaleProbe:
        fail(f"probe '{label}': NO-OP MUTATION (pattern absent from the live "
             f"'{shape}' source) — probe is stale, failing self-check")
    if new_cpp == cpp_text and new_hdr == hdr_text:
        fail(f"probe '{label}': NO-OP MUTATION — probe is stale, failing "
             f"self-check")
    try:
        check(new_cpp, new_hdr)
    except Reject:
        print(f"midi-learn-capture probe '{label}': rejected as expected")
        return
    fail(f"probe '{label}' was NOT rejected — {why}")


COMMON_PROBES = [
    ("flag-clear stripped",
     "the capture branch must clear midiLearnActive after capturing",
     [(r"(midiMap\s*\[\s*cc\s*\]\s*=\s*midiLearnParamID;)\s*"
       r"midiLearnActive\s*=\s*false;", r"\1")]),
    ("midiMap write moved out of the lock",
     "the captured-CC write must stay inside the held midiMapLock block",
     [(r"capturedCc\s*=\s*cc;\s*\n\s*midiMap\s*\[\s*cc\s*\]\s*=\s*"
       r"midiLearnParamID;", "capturedCc = cc;")]),
    ("setValueNotifyingHost re-added in capture",
     "capture must not jump the host value inside the lock",
     [(r"(midiMap\s*\[\s*cc\s*\]\s*=\s*midiLearnParamID;)",
       r"\1\n p->setValueNotifyingHost(0.0f);")]),
    ("refuse-to-steal guard removed",
     "an already-mapped foreign CC must not be silently stolen",
     [(r"auto existing = midiMap\.find\(cc\);\s*if \(existing != "
       r"midiMap\.end\(\) && existing->second != midiLearnParamID\)\s*"
       r"continue;\s*", "")]),
    ("different-param comparison removed",
     "the guard must compare against a DIFFERENT parameter",
     [(r"existing->second != midiLearnParamID",
       "existing->second == midiLearnParamID")]),
    ("host notification inserted under the lock",
     "setValueNotifyingHost must never run while midiMapLock is held",
     [(r"(midiMap\s*\[\s*cc\s*\]\s*=\s*midiLearnParamID;)",
       r"\1\n apvts.getParameter(midiLearnParamID)"
       r"->setValueNotifyingHost(0.0f);")]),
]

OLD_SHAPE_PROBES = [
    ("snapshot copy dropped from the lock block",
     "the midiMap snapshot must be copied under the lock",
     [(r"mapSnapshot\s*=\s*midiMap\s*;", "(void) 0;")]),
    ("apply path reverted to the live midiMap",
     "the post-lock apply path must read the snapshot, not midiMap",
     [(r"(=\s*)mapSnapshot\s*\.\s*find\s*\(\s*cc\s*\)",
       r"\1midiMap.find(cc)")]),
]

NEW_SHAPE_PROBES = [
    ("off-thread capacity shrunk to 1",
     "reserve(1) cannot hold the 128-entry CC domain",
     [(r"mapSnapshot\s*\.\s*reserve\s*\(\s*[0-9]+\s*\)",
       "mapSnapshot.reserve(1);")]),
    ("capacity guard removed from the refill",
     "an unguarded append can outgrow the reservation",
     [(r"if\s*\(\s*cc\s*>=\s*0\s*&&\s*cc\s*(?:<=\s*127|<\s*128)\s*\)\s*\n\s*",
       "")]),
    ("reserve moved onto the audio thread",
     "capacity must be established off-thread only",
     [RESERVE_AT_REFILL]),
    ("clear dropped from the refill",
     "stale entries would accumulate every block",
     [(r"mapSnapshot\s*\.\s*clear\s*\(\s*\)\s*;", "")]),
    ("mapSnapshot shadowed by a local vector",
     "a local vector allocates on the audio thread",
     [SHADOW_AT_REFILL]),
    ("apply path reverted to the live midiMap",
     "the post-lock apply path must scan the preallocated snapshot",
     [(r":\s*mapSnapshot\s*\)", ": midiMap)")]),
]

APPLICABLE = COMMON_PROBES + (
    OLD_SHAPE_PROBES if shape == "local-map" else NEW_SHAPE_PROBES)
for label, why, cpp_mutations in APPLICABLE:
    live_probe(label, why, cpp_mutations=cpp_mutations)


# ---------------------------------------------------------------------------
# Positive fixtures for both representations
# ---------------------------------------------------------------------------
expect_ok("local-map snapshot (master shape)",
          FIXTURE_OLD_CPP, FIXTURE_OLD_HEADER, "local-map")
expect_ok("preallocated member-vector snapshot (CV-017 shape)",
          FIXTURE_NEW_CPP, FIXTURE_NEW_HEADER, "member-vector")
expect_ok("member-vector with an earlier message-thread midiMapLock",
          FIXTURE_NEW_MULTILOCK_CPP, FIXTURE_NEW_HEADER, "member-vector")


# ---------------------------------------------------------------------------
# Negative fixture mutations (each must be rejected)
# ---------------------------------------------------------------------------
c, h = fixture_mutation(
    "reserve(1) insufficient capacity",
    cpp_mutations=[(r"mapSnapshot\.reserve\(128\);",
                    "mapSnapshot.reserve(1);")])
expect_fixture_reject(
    "reserve(1) insufficient capacity", c, h,
    "capacity below the 128-entry CC domain must fail")

c, h = fixture_mutation(
    "absent capacity guard",
    cpp_mutations=[(r"if \(cc >= 0 && cc <= 127\)\s*\n\s*", "")])
expect_fixture_reject(
    "absent capacity guard", c, h,
    "an unbounded refill must fail even when reserve(128) is present")

c, h = fixture_mutation(
    "reserve inside processBlock",
    cpp_mutations=[(r"(const juce::ScopedLock lock\(midiMapLock\);)",
                    r"\1\n mapSnapshot.reserve(128);")])
expect_fixture_reject(
    "reserve inside processBlock", c, h,
    "audio-thread capacity work must fail")

# CV-017 regression: the audio-thread mutations must reach processBlock even
# when an earlier message-thread ScopedLock(midiMapLock) precedes it.
c, h = fixture_mutation(
    "reserve in processBlock (multi-lock source)",
    cpp_mutations=[RESERVE_AT_REFILL],
    cpp=FIXTURE_NEW_MULTILOCK_CPP, hdr=FIXTURE_NEW_HEADER)
expect_fixture_reject(
    "reserve in processBlock (multi-lock source)", c, h,
    "the audio-thread reserve probe must anchor on the processBlock refill, "
    "not the earlier message-thread lock")

c, h = fixture_mutation(
    "local vector shadowing mapSnapshot (multi-lock source)",
    cpp_mutations=[SHADOW_AT_REFILL],
    cpp=FIXTURE_NEW_MULTILOCK_CPP, hdr=FIXTURE_NEW_HEADER)
expect_fixture_reject(
    "local vector shadowing mapSnapshot (multi-lock source)", c, h,
    "the shadowing probe must anchor on the processBlock refill, not the "
    "earlier message-thread lock")

# Guard the fixture itself: a probe still anchored on the FIRST midiMapLock
# would rewrite only the earlier message-thread lock and leave processBlock
# accepted. This fixture must expose exactly that (so the old anchor fails the
# two rejections above instead of passing silently).
c, h = fixture_mutation(
    "legacy first-lock reserve anchor (multi-lock fixture guard)",
    cpp_mutations=[
        (OLD_FIRST_LOCK_ANCHOR, r"\1\n mapSnapshot.reserve(128);")],
    cpp=FIXTURE_NEW_MULTILOCK_CPP, hdr=FIXTURE_NEW_HEADER)
expect_ok("legacy first-lock reserve anchor (multi-lock fixture guard)",
          c, h, "member-vector")

c, h = fixture_mutation(
    "legacy first-lock shadow anchor (multi-lock fixture guard)",
    cpp_mutations=[
        (OLD_FIRST_LOCK_ANCHOR,
         r"std::vector<std::pair<int, juce::String>> mapSnapshot;\n \1")],
    cpp=FIXTURE_NEW_MULTILOCK_CPP, hdr=FIXTURE_NEW_HEADER)
expect_ok("legacy first-lock shadow anchor (multi-lock fixture guard)",
          c, h, "member-vector")

c, h = fixture_mutation(
    "capture write outside the lock",
    cpp_mutations=[
        (r"midiMap\[cc\] = midiLearnParamID;\s*\n\s*midiLearnActive",
         "midiLearnActive"),
        (r"(if \(cc == capturedCc\)\s*continue;)",
         r"midiMap[cc] = midiLearnParamID;\n \1"),
    ])
expect_fixture_reject(
    "capture write outside the lock", c, h,
    "the captured-CC write must stay under the held lock")

c, h = fixture_mutation(
    "host notification under the lock",
    cpp_mutations=[(r"(midiMap\[cc\] = midiLearnParamID;)",
                    r"\1\n apvts.getParameter(midiLearnParamID)"
                    r"->setValueNotifyingHost(0.0f);")])
expect_fixture_reject(
    "host notification under the lock", c, h,
    "host notification must never run inside the critical section")

c, h = fixture_mutation(
    "lost flag clear",
    cpp_mutations=[(r"\s*midiLearnActive = false;", "")])
expect_fixture_reject(
    "lost flag clear", c, h,
    "the capture branch must clear midiLearnActive")

c, h = fixture_mutation(
    "lost refuse-to-steal",
    cpp_mutations=[(r"auto existing = midiMap\.find\(cc\);\s*if \(existing "
                    r"!= midiMap\.end\(\) && existing->second != "
                    r"midiLearnParamID\)\s*continue;\s*", "")])
expect_fixture_reject(
    "lost refuse-to-steal", c, h,
    "the different-parameter refusal must stay in the capture branch")

# the local-map shape keeps its own snapshot-copy assertion
c, h = fixture_mutation(
    "local-map snapshot copy dropped",
    cpp_mutations=[(r"mapSnapshot\s*=\s*midiMap\s*;", "(void) 0;")],
    cpp=FIXTURE_OLD_CPP, hdr=FIXTURE_OLD_HEADER)
expect_fixture_reject(
    "local-map snapshot copy dropped", c, h,
    "the local-map snapshot must be copied under the lock")

# header member dropped -> the member-vector shape must no longer be accepted
c, h = fixture_mutation(
    "member header declaration dropped",
    hdr_mutations=[(r"\s*std::vector<std::pair<int, juce::String>> "
                     r"mapSnapshot;", "")])
expect_fixture_reject(
    "member header declaration dropped", c, h,
    "the member-vector shape must require the processor member")

# shadowing: member stays in the header, a local map appears in processBlock
c, h = fixture_mutation(
    "member shadowed by a local std::map",
    cpp_mutations=[(r"(int capturedCc = -1;)",
                    r"std::map<int, juce::String> mapSnapshot;\n \1")])
expect_fixture_reject(
    "member shadowed by a local std::map", c, h,
    "a local that shadows the preallocated member must fail")


# ---------------------------------------------------------------------------
# Stale/no-op probe detection self-test (no-op detection must stay enabled)
# ---------------------------------------------------------------------------
try:
    mutate(FIXTURE_NEW_CPP, r"pattern_that_is_absent_9f3c", "x",
           "stale probe self-test")
except StaleProbe:
    print("midi-learn-capture: stale/no-op probe detection proven "
          "(absent pattern refuses to pass silently)")
else:
    fail("stale/no-op probe was NOT detected — no-op detection is disabled")


# ---------------------------------------------------------------------------
# Final live re-verification (the real tree was never written to)
# ---------------------------------------------------------------------------
try:
    final_shape = check(CPP.read_text(encoding="utf-8"),
                        HDR.read_text(encoding="utf-8"))
except Reject as exc:
    fail(f"final source re-verification failed: {exc}")
if final_shape != shape:
    fail(f"live snapshot shape changed mid-run: '{shape}' -> '{final_shape}'")
print(f"MIDI-LEARN-CAPTURE OK ({shape})")
