
# iter-133 - refill turn (2 FILE, 2 DROP; root cause of the 7-round DROP signature fixed)

item:    refill turn — zero open [ ] in Ready and no FORCE markers, so
         SKIP was written to .sprint/SUBJECT.txt BEFORE any other
         write, per charter.
did:     jev-refill brief (EXIT 0) again names ONLY the excluded
         ALREADY-APPLIED source/DrippyFX/scripts/fix_*.py Windows
         migration scripts — 11th consecutive round. Before
         re-submitting the same 4 candidates from
         .sprint/CANDIDATES.md, root-caused the recurring
         "premise p=0.03" DROP signature (iters-106/118/123/128/130/
         131/132): grade-queue.py parse_queue only treats INDENTED
         lines as item-body continuations, and CANDIDATES.md placed
         every continuation line at column 0 — so each candidate's
         graded text was ONLY its first sentence, zero `path:NN`
         citations were extracted, the grader received no
         cited_code excerpts, and premise low-scored faultlessly.
         Re-verified all 4 candidates' premises verbatim on disk
         THIS turn (PluginProcessor.cpp:295-298/:300-303/:305;
         :44-46; :57/:171/:354/:365/:376/:395; :850/:864), then
         re-indented CANDIDATES.md item bodies (2-space continuations,
         metadata-only change, zero repo code touched). Extraction
         re-probe: 3/2/2/2 citations now load per candidate.
         jev-refill grade (EXIT 0): 2 FILE, 2 DROP —
         abSlots if-init guard shape (substance 0.60) and the
         A/B Compare 4-banner undo-transaction roster (0.54) FILED
         verbatim at the top of BACKLOG Ready with must-keep +
         outcome lines; program-contract trio (impact 0.48) and
         parameterChanged guard (0.47 < 0.5 substance bar) DROPped
         honestly and remain in CANDIDATES.md. Phase 1 stays.
gate:    bash .sprint/verify-gate.sh -> GATE_OK EXIT=0 captured
         directly.
files:   .sprint/SUBJECT.txt, .sprint/CANDIDATES.md (indent fix),
         .sprint/BACKLOG.md (2 filed items), this journal.
outcome: This change achieves refill integrity because the 7-round
         DROP verdicts are explained by a mechanical citation-
         extraction defect and fixed at its root, two grader-FILEd
         candidates now sit in Ready for the next iteration with
         their premises re-verified on disk, and the two honest
         DROPs remain recorded without hand-override.
