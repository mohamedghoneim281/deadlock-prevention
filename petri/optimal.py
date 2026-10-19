"""Exact optimal makespan over ALL dispatch policies (including deliberate idling).

State = (marking, remaining time of each running timer).  From a state a controller may
  (a) fire any enabled immediate (controllable) transition now, or
  (b) let time advance to the next timer expiry, which fires every expiring machine event.
Memoised depth-first search returns the minimum time to reach the completed-batch marking
(inf if the batch can never complete).  Because it ranges over every controller choice, it is a
lower bound for any supervisor/dispatcher on the *unrestricted* plant with all parts at t=0.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from typing import Tuple

from .cell import is_final
from .net import Marking, PetriNet

INF = float("inf")


def optimal_makespan(net: PetriNet, batch: Tuple[int, int] = (2, 2)) -> float:
    """`net` must be preloaded (the whole batch is in the queues at t=0)."""
    sys.setrecursionlimit(10_000)
    T = len(net.transitions)
    timed = [i for i in range(T) if net.transitions[i].delay > 0]
    imm = [i for i in range(T) if net.transitions[i].delay == 0]

    def normalise(m: Marking, rem: Tuple[int, ...]) -> Tuple[int, ...]:
        out = []
        for j, ti in enumerate(timed):
            en = net.is_enabled(m, ti)
            if en:
                out.append(rem[j] if rem[j] >= 0 else net.transitions[ti].delay)
            else:
                out.append(-1)
        return tuple(out)

    @lru_cache(maxsize=None)
    def f(m: Marking, rem: Tuple[int, ...]) -> float:
        if is_final(net, m, batch):
            return 0.0
        best = INF
        for ti in imm:                                   # (a) act now
            if net.is_enabled(m, ti):
                m2 = net.fire(m, ti)
                best = min(best, f(m2, normalise(m2, rem)))
        active = [r for r in rem if r >= 0]
        if active:                                       # (b) wait for the next machine event
            d = min(active)
            m3 = m
            rem3 = []
            for j, ti in enumerate(timed):
                if rem[j] == d:
                    m3 = net.fire(m3, ti)
                    rem3.append(-1)
                elif rem[j] > d:
                    rem3.append(rem[j] - d)
                else:
                    rem3.append(-1)
            best = min(best, d + f(m3, normalise(m3, tuple(rem3))))
        return best

    m0 = net.initial_marking
    return f(m0, normalise(m0, tuple(-1 for _ in timed)))
