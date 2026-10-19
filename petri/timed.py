"""Deterministic discrete-event simulator for the timed net.

Semantics (shared, rule for rule, with the C++ engine -- see cpp/):
  * time is integer ticks;
  * a transition with delay > 0 ("timed") has a single timer that starts when it becomes
    enabled and fires ``delay`` ticks later (single-server, enabling memory);
  * a transition with delay == 0 ("immediate") is fired by the dispatcher.
At each event time t the simulator does, in this order:
  1. inject external arrivals scheduled for t           (log: ARRIVE)
  2. fire timed transitions whose timer expires at t,   in net order (log: FIRE)
  3. dispatch: repeatedly fire the FIRST enabled immediate transition in net order
     until none is enabled                              (log: FIRE)
  4. (re)start timers of newly enabled timed transitions, drop timers of disabled ones
The run ends when no timer and no arrival is pending: DONE if the whole batch is unloaded,
DEADLOCK otherwise.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .cell import ProcTimes, is_final
from .net import Marking, PetriNet

Arrival = Tuple[int, str, int]  # (time, place, count)


@dataclass
class SimResult:
    status: str                      # "DONE" | "DEADLOCK"
    end_time: int
    final_marking: Marking
    log: List[str] = field(default_factory=list)

    @property
    def deadlock(self) -> bool:
        return self.status == "DEADLOCK"


MAX_STEPS = 100_000


def simulate(net: PetriNet, arrivals: Sequence[Arrival], batch=(2, 2),
             record: bool = True) -> SimResult:
    arr = sorted(arrivals, key=lambda a: a[0])  # stable: ties keep given order
    ai = 0
    m = net.initial_marking
    T = len(net.transitions)
    delay = [t.delay for t in net.transitions]
    timer: Dict[int, int] = {}
    log: List[str] = []
    t = 0
    steps = 0

    def do_arrivals(now: int) -> None:
        nonlocal ai, m
        while ai < len(arr) and arr[ai][0] == now:
            _, place, n = arr[ai]
            lst = list(m)
            lst[net.pidx[place]] += n
            m = tuple(lst)
            if record:
                log.append(f"{now} ARRIVE {place} {n}")
            ai += 1

    do_arrivals(0)
    while True:
        # 2. expired timers
        for ti in range(T):
            if timer.get(ti) == t:
                assert net.is_enabled(m, ti), "timed transition lost its enabling"
                m = net.fire(m, ti)
                del timer[ti]
                if record:
                    log.append(f"{t} FIRE {net.transitions[ti].name}")
        # 3. dispatch
        while True:
            for ti in range(T):
                if delay[ti] == 0 and net.is_enabled(m, ti):
                    m = net.fire(m, ti)
                    if record:
                        log.append(f"{t} FIRE {net.transitions[ti].name}")
                    steps += 1
                    break
            else:
                break
            if steps > MAX_STEPS:
                raise RuntimeError("dispatch did not terminate")
        # 4. timers
        for ti in range(T):
            if delay[ti] > 0:
                en = net.is_enabled(m, ti)
                if en and ti not in timer:
                    timer[ti] = t + delay[ti]
                elif not en and ti in timer:
                    del timer[ti]
        # next event time
        cands = list(timer.values())
        if ai < len(arr):
            cands.append(arr[ai][0])
        if not cands:
            break
        t = min(cands)
        do_arrivals(t)

    status = "DONE" if is_final(net, m, batch) else "DEADLOCK"
    if record:
        log.append(f"END {t} {status}")
    return SimResult(status, t, m, log)


# ---------------------------------------------------------------- metrics
def _times(log: Sequence[str]) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for line in log:
        f = line.split()
        if f[1] == "FIRE":
            out.setdefault(f[2], []).append(int(f[0]))
    return out


def metrics(res: SimResult, arrivals: Sequence[Arrival], times: ProcTimes) -> Dict[str, float]:
    """Per-batch metrics from the firing log (FIFO pairing per product: parts never overtake
    each other because each stage has one machine and one FIFO queue)."""
    ft = _times(res.log)
    arr_a = sorted(a[0] for a in arrivals if a[1] == "A_queue" for _ in range(a[2]))
    arr_b = sorted(a[0] for a in arrivals if a[1] == "B_queue" for _ in range(a[2]))
    g = lambda k: ft.get(k, [])
    nan = float("nan")
    out: Dict[str, float] = {"deadlock": float(res.deadlock)}
    done_a, done_b = g("A_unload"), g("B_unload")
    if res.deadlock:   # same schema as a completed run; undefined quantities are NaN
        out.update(makespan=nan, util_m1=nan, util_m2=nan, blocked_m1=nan, blocked_m2=nan,
                   mean_wait=nan, mean_flow=nan)
        return out
    makespan = max(done_a + done_b)
    # queue wait: arrival -> load (includes waiting for machine and for control permission)
    wait = [l - a for l, a in zip(g("A_load"), arr_a)] + [l - a for l, a in zip(g("B_load"), arr_b)]
    flow = [u - a for u, a in zip(done_a, arr_a)] + [u - a for u, a in zip(done_b, arr_b)]
    # blocking: finished on a machine but still holding it
    blocked_m1 = (sum(x - d for x, d in zip(g("A_xfer"), g("A_done_M1")))
                  + sum(u - d for u, d in zip(g("B_unload"), g("B_done_M1"))))
    blocked_m2 = (sum(x - d for x, d in zip(g("B_xfer"), g("B_done_M2")))
                  + sum(u - d for u, d in zip(g("A_unload"), g("A_done_M2"))))
    busy_m1 = len(g("A_done_M1")) * times.a_m1 + len(g("B_done_M1")) * times.b_m1
    busy_m2 = len(g("A_done_M2")) * times.a_m2 + len(g("B_done_M2")) * times.b_m2
    out.update(
        makespan=float(makespan),
        util_m1=busy_m1 / makespan,
        util_m2=busy_m2 / makespan,
        blocked_m1=float(blocked_m1),
        blocked_m2=float(blocked_m2),
        mean_wait=sum(wait) / len(wait),
        mean_flow=sum(flow) / len(flow),
    )
    return out


def intervals(res: SimResult, times: ProcTimes,
              horizon: Optional[int] = None) -> List[Tuple[str, str, str, int, int]]:
    """Machine occupancy intervals (machine, product, kind, start, end) for Gantt plots.
    kind is 'proc' (processing) or 'hold' (finished, still holding the machine).
    Holds that never end (deadlock) are drawn up to max(res.end_time, horizon)."""
    ft = _times(res.log)
    g = lambda k: ft.get(k, [])
    out: List[Tuple[str, str, str, int, int]] = []

    def stage(machine, prod, start_key, done_key, release_key, ptime):
        starts, dones, rels = g(start_key), g(done_key), g(release_key)
        for i, s in enumerate(starts):
            d = dones[i] if i < len(dones) else s + ptime
            out.append((machine, prod, "proc", s, d))
            if i < len(dones):
                r = rels[i] if i < len(rels) else max(res.end_time, horizon or 0)
                if r > d:
                    out.append((machine, prod, "hold", d, r))

    stage("M1", "A", "A_load", "A_done_M1", "A_xfer", times.a_m1)
    stage("M2", "A", "A_xfer", "A_done_M2", "A_unload", times.a_m2)
    stage("M2", "B", "B_load", "B_done_M2", "B_xfer", times.b_m2)
    stage("M1", "B", "B_xfer", "B_done_M1", "B_unload", times.b_m1)
    return sorted(out, key=lambda x: (x[0], x[3]))
