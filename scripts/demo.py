"""Console walk-through for the 90-second demonstration: failure -> intervention -> verification.

Usage:  python3 scripts/demo.py            (pauses are skipped; add --slow to wait for <Enter>)
"""
import subprocess
import sys

from _common import ROOT
from petri.analysis import deadlock_indices, reachability, trace_to
from petri.cell import ProcTimes, build_cell, is_final
from petri.engine_io import ENGINE, EngineSession, engine_available
from petri.timed import simulate
from petri.verify import verify_all

SLOW = "--slow" in sys.argv


def pause():
    if SLOW:
        input("   [Enter] ")


def show(net, m, label):
    held = ", ".join(f"{p}={v}" for p, v in net.marking_dict(m).items() if p not in ("A_out", "B_out"))
    print(f"   {label:<18} {held}")


def act1():
    print("\n=== ACT 1  Unrestricted dispatch: the circular wait ===")
    net = build_cell("unrestricted")
    g = reachability(net)
    dl = deadlock_indices(g, lambda m: is_final(net, m))
    trace = trace_to(g, dl[0])
    m = net.initial_marking
    show(net, m, "start")
    for name in trace:
        m = net.fire(m, net.tidx[name])
        show(net, m, name)
        pause()
    print(f"   -> enabled transitions: {net.enabled(m) or 'NONE'}   unfinished parts: "
          f"{4 - m[net.pidx['A_out']] - m[net.pidx['B_out']]}")
    print("   A (finished on M1) needs M2; B (finished on M2) needs M1. Each holds what the other needs.")
    print(f"   Reachable markings: {g.size}; terminal deadlocks: {len(dl)}")


def act2():
    print("\n=== ACT 2  Same commands with the control place ===")
    net = build_cell("supervisor")
    m = net.initial_marking
    show(net, m, "start (CTRL=1)")
    for name in ("A_load", "B_load"):
        t = net.tidx[name]
        if net.is_enabled(m, t):
            m = net.fire(m, t)
            show(net, m, name)
        else:
            print(f"   {name:<18} REFUSED: CTRL has no token (A_load holds the permission until A_xfer)")
        pause()
    ones = ProcTimes(4, 4, 4, 4)
    arr = [(0, "A_queue", 2), (0, "B_queue", 2)]
    for pol in ("unrestricted", "one_active", "supervisor"):
        r = simulate(build_cell(pol, times=ones, preload=False), arr)
        print(f"   timed run, {pol:<12}: {r.status} at t={r.end_time}")


def act3():
    print("\n=== ACT 3  Verification ===")
    v = verify_all()
    for pol, d in v["policies"].items():
        print(f"   {pol:<13} markings={d['reachable_markings']:>3}  deadlocks={d['deadlocks_with_unfinished_jobs']}  "
              f"cannot-complete={d['markings_that_cannot_complete']:>2}  invariants hold={d['invariants_hold_on_all_markings']}")
    ref = v["maximally_permissive_reference"]
    print(f"   supervisor equals maximally permissive safe behaviour: {ref['supervisor']['equals_maximally_permissive']} "
          f"({ref['reachable_markings']} markings; one-active gives up {ref['one_active']['safe_states_given_up']})")
    if engine_available():
        net = build_cell("supervisor", times=ProcTimes(4, 4, 4, 4), preload=False)
        arr = [(0, "A_queue", 2), (0, "B_queue", 2)]
        s = EngineSession(net)
        cpp = s.simulate(arr)
        s.close()
        same = cpp == simulate(net, arr).log
        print(f"   C++ engine vs Python on the same run: logs identical = {same}  ({len(cpp)} log lines)")
    else:
        print("   (C++ engine not built - run `make` to include the C++ comparison)")


if __name__ == "__main__":
    act1(); act2(); act3()
