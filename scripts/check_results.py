"""Final PASS/FAIL summary of the headline claims, read from the generated result files.

Run automatically at the end of `make reproduce`.  Exit code 0 only if every check passes.
"""
import sys

from _common import load_json


def main() -> int:
    v = load_json("verification.json")
    ex = load_json("experiments_summary.json")
    cc = load_json("crosscheck.json")
    bm = load_json("benchmark.json")
    P = v["policies"]
    ref = v["maximally_permissive_reference"]
    e1, e2 = ex["exp1"], ex["exp2"]
    checks = [
        ("Unrestricted cell: 97 reachable markings, 4 deadlocks",
         P["unrestricted"]["reachable_markings"] == 97 and P["unrestricted"]["deadlocks_with_unfinished_jobs"] == 4),
        ("One-active-part policy: 57 markings, 0 deadlocks",
         P["one_active"]["reachable_markings"] == 57 and P["one_active"]["deadlocks_with_unfinished_jobs"] == 0),
        ("Control-place supervisor: 81 markings, 0 deadlocks, batch always completable",
         P["supervisor"]["reachable_markings"] == 81 and P["supervisor"]["deadlocks_with_unfinished_jobs"] == 0
         and P["supervisor"]["every_marking_can_complete"]),
        ("Invariants hold on every reachable marking (all 3 policies)",
         all(d["invariants_hold_on_all_markings"] for d in P.values())),
        ("Supervisor equals the maximally permissive safe behaviour",
         ref["supervisor"]["equals_maximally_permissive"]),
        ("Timed grid: unrestricted deadlocks in all 162 scenarios",
         e1["unrestricted_deadlocked"] == e1["runs_per_policy"] == 162),
        ("Timed grid: supervisor never slower than one-active, closed-form saving matches",
         e1["supervisor_vs_one_active"]["never_slower"] and e1["supervisor_vs_one_active"]["closed_form_saving_matches_all"]),
        ("Timed grid: supervisor reaches the exact optimum in all 162 scenarios",
         e1["supervisor_vs_optimal"]["runs_at_optimum"] == 162),
        ("Monte Carlo: 0 deadlocks in all controlled runs",
         sum(r["controlled_deadlocks"] for r in e2) == 0),
        ("Python vs C++: 0 mismatches in simulations, replays and rejected-command tests", cc["ok"]),
        ("C++ engine is faster than the Python reference", all(c["speedup"] > 1 for c in bm["cases"])),
    ]
    width = max(len(n) for n, _ in checks)
    print("\n" + "=" * (width + 10))
    print(" FINAL CHECK")
    print("=" * (width + 10))
    for name, ok in checks:
        print(f" [{'PASS' if ok else 'FAIL'}] {name}")
    all_ok = all(ok for _, ok in checks)
    print("=" * (width + 10))
    env = bm["environment"]
    print(f" Machine: {env['cpu']} ({env.get('machine', '?')})")
    for c in bm["cases"]:
        print(f" C++ engine, {c['label']}: {c['cpp']['mean_run_ns'] / 1e3:.2f} us per run, "
              f"peak memory {c['cpp']['peak_rss_kb'] / 1024:.1f} MB")
    print("=" * (width + 10))
    print(" ALL CHECKS PASSED" if all_ok else " SOME CHECKS FAILED - do not use these results")
    print("=" * (width + 10))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
