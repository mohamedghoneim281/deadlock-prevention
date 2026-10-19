"""Python <-> C++ cross-validation.

Two independent implementations of the same net semantics must agree
  * on every timed simulation log (byte for byte), and
  * after every step of every replayed event sequence: marking AND set of enabled transitions.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .analysis import deadlock_indices, reachability, trace_to
from .cell import POLICIES, ProcTimes, build_cell, is_final
from .engine_io import EngineSession
from .net import Marking, PetriNet
from .timed import Arrival, simulate


# ------------------------------------------------------------ Python reference replay
def _enabled_str(net: PetriNet, m: Marking) -> str:
    names = [net.transitions[t].name for t in net.enabled(m)]
    return ",".join(names) if names else "-"


def py_replay(net: PetriNet, trace: Sequence[str]) -> Tuple[int, List[str]]:
    """Reference implementation of `petri_engine replay` (same output format)."""
    m = net.initial_marking
    step = 0
    out = [f"0|INIT|{','.join(map(str, m))}|{_enabled_str(net, m)}"]
    for line in trace:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tok = line.split()
        if tok[0].lstrip("-").isdigit():
            tok = tok[1:]
        if tok[0] == "END":
            continue
        step += 1
        if tok[0] == "FIRE":
            t = net.tidx.get(tok[1])
            if t is None or not net.is_enabled(m, t):
                out.append(f"ERROR|{step}|{tok[1]}|not enabled")
                return 2, out
            m = net.fire(m, t)
            label = f"FIRE {tok[1]}"
        elif tok[0] == "ARRIVE":
            lst = list(m)
            lst[net.pidx[tok[1]]] += int(tok[2])
            m = tuple(lst)
            label = f"ARRIVE {tok[1]} {tok[2]}"
        else:
            raise ValueError(line)
        out.append(f"{step}|{label}|{','.join(map(str, m))}|{_enabled_str(net, m)}")
    return 0, out


def random_walk(net: PetriNet, rng: random.Random, max_steps: int = 200) -> List[str]:
    """Random firing sequence (untimed): pick uniformly among enabled transitions until none."""
    m = net.initial_marking
    trace = []
    for _ in range(max_steps):
        en = net.enabled(m)
        if not en:
            break
        t = rng.choice(en)
        trace.append(f"FIRE {net.transitions[t].name}")
        m = net.fire(m, t)
    return trace


# ------------------------------------------------------------ campaign
@dataclass
class CrossCheckReport:
    simulate_runs: int = 0
    simulate_mismatches: int = 0
    replay_traces: int = 0
    replay_steps: int = 0
    replay_mismatches: int = 0
    deadlock_traces: int = 0
    negative_tests: int = 0
    negative_failures: int = 0
    details: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return (self.simulate_mismatches == 0 and self.replay_mismatches == 0
                and self.negative_failures == 0)

    def as_dict(self) -> Dict[str, object]:
        d = dict(self.__dict__)
        d["ok"] = self.ok
        d["details"] = self.details[:20]
        return d


def random_scenario(rng: random.Random, spread: int):
    times = ProcTimes(*(rng.randint(1, 9) for _ in range(4)))
    arrivals: List[Arrival] = []
    for place in ("A_queue", "A_queue", "B_queue", "B_queue"):
        arrivals.append((rng.randint(0, spread), place, 1))
    order = rng.choice([("A", "B"), ("B", "A")])
    return times, arrivals, order


def run_crosscheck(n_sim: int = 300, n_walks: int = 100, seed: int = 2026) -> CrossCheckReport:
    rng = random.Random(seed)
    rep = CrossCheckReport()

    # (1) timed simulation logs, random processing times / arrival patterns / dispatch priorities
    for i in range(n_sim):
        times, arrivals, order = random_scenario(rng, spread=rng.choice([0, 3, 10, 30]))
        for pol in POLICIES:
            net = build_cell(pol, times=times, load_order=order, preload=False)
            sess = EngineSession(net)
            try:
                py = simulate(net, arrivals).log
                cpp = sess.simulate(arrivals)
                rep.simulate_runs += 1
                if py != cpp:
                    rep.simulate_mismatches += 1
                    rep.details.append(f"sim mismatch seed-iter {i} policy {pol}")
                # (2c) replay the timed log (ARRIVE/FIRE events) through both implementations
                rc_py, out_py = py_replay(net, py)
                rc_cpp, out_cpp = sess.replay(py)
                rep.replay_traces += 1
                rep.replay_steps += len(out_py)
                if rc_py != 0 or rc_cpp != 0 or out_py != out_cpp:
                    rep.replay_mismatches += 1
                    rep.details.append(f"timed-log replay mismatch iter {i} policy {pol}")
            finally:
                sess.close()

    # (2a/2b) untimed: shortest trace to deadlock + random walks on each policy's preloaded net
    for pol in POLICIES:
        net = build_cell(pol)
        sess = EngineSession(net)
        try:
            g = reachability(net)
            dl = deadlock_indices(g, lambda m, net=net: is_final(net, m))
            traces: List[List[str]] = []
            if dl:
                traces.append([f"FIRE {n}" for n in trace_to(g, dl[0])])
                rep.deadlock_traces += 1
            traces += [random_walk(net, rng) for _ in range(n_walks)]
            for tr in traces:
                rc_py, out_py = py_replay(net, tr)
                rc_cpp, out_cpp = sess.replay(tr)
                rep.replay_traces += 1
                rep.replay_steps += len(out_py)
                if rc_py != rc_cpp or out_py != out_cpp:
                    rep.replay_mismatches += 1
                    rep.details.append(f"walk mismatch policy {pol}: {tr[:6]}")
                # a walk that stops early must stop in a true terminal marking for both
            # (3) negative tests: illegal firings must be rejected identically
            bad_traces = [
                ["FIRE A_xfer"],                                  # nothing to transfer yet
                ["FIRE A_load", "FIRE A_xfer"],                   # transfer before processing finished
                ["FIRE A_load", "FIRE A_load"],                   # M1 already held
                ["FIRE NO_SUCH_TRANSITION"],
            ]
            if pol != "unrestricted":
                # control place: after A_load the permission token is gone, so B_load must be refused
                bad_traces.append(["FIRE A_load", "FIRE B_load"])
            for tr in bad_traces:
                rc_py, out_py = py_replay(net, tr)
                rc_cpp, out_cpp = sess.replay(tr)
                rep.negative_tests += 1
                if not (rc_py == 2 and rc_cpp == 2 and out_py == out_cpp):
                    rep.negative_failures += 1
                    rep.details.append(f"negative test failed policy {pol}: {tr}")
        finally:
            sess.close()
    return rep
