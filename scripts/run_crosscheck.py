"""Python <-> C++ cross-validation -> results/crosscheck.json"""
import sys

from _common import save_json
from petri.crosscheck import run_crosscheck
from petri.engine_io import engine_available


def main() -> int:
    if not engine_available():
        print("C++ engine not built: run `make` first", file=sys.stderr)
        return 1
    rep = run_crosscheck(n_sim=300, n_walks=100)
    d = rep.as_dict()
    save_json("crosscheck.json", d)
    print(f"timed simulations compared: {d['simulate_runs']}  mismatches: {d['simulate_mismatches']}")
    print(f"replayed sequences: {d['replay_traces']} ({d['replay_steps']} steps; includes {d['deadlock_traces']} deadlock traces)  "
          f"mismatches: {d['replay_mismatches']}")
    print(f"negative tests (illegal firing must be rejected by both): {d['negative_tests']}  failures: {d['negative_failures']}")
    print("CROSS-CHECK", "PASSED" if d["ok"] else "FAILED")
    return 0 if d["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
