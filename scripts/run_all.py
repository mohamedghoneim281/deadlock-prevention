"""Regenerate everything: build -> tests -> verification -> experiments -> cross-check -> benchmark -> figures -> report."""
import subprocess
import sys
import time

from _common import ROOT

STEPS = [
    ("build C++ engine", ["make", "-C", str(ROOT)]),
    ("unit tests", [sys.executable, "-m", "pytest", "-q", str(ROOT / "tests")]),
    ("exhaustive verification", [sys.executable, str(ROOT / "scripts" / "run_verification.py")]),
    ("timed experiments", [sys.executable, str(ROOT / "scripts" / "run_experiments.py")]),
    ("Python <-> C++ cross-check", [sys.executable, str(ROOT / "scripts" / "run_crosscheck.py")]),
    ("benchmark (machine-dependent)", [sys.executable, str(ROOT / "scripts" / "run_benchmark.py")]),
    ("figures", [sys.executable, str(ROOT / "scripts" / "make_figures.py")]),
    ("results report", [sys.executable, str(ROOT / "scripts" / "make_report.py")]),
    ("final check", [sys.executable, str(ROOT / "scripts" / "check_results.py")]),
]

if __name__ == "__main__":
    t0 = time.time()
    for name, cmd in STEPS:
        print(f"\n##### {name}", flush=True)
        r = subprocess.run(cmd, cwd=ROOT / "scripts")
        if r.returncode != 0:
            print(f"\nFAILED at step: {name}", file=sys.stderr)
            sys.exit(r.returncode)
    print(f"\nAll steps finished in {time.time() - t0:.0f} s. Results: results/RESULTS.md   Figures: figures/")
