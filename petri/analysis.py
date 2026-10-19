"""Untimed analysis: reachability graph, deadlocks, invariants, nonblocking check,
and the maximally permissive safe behaviour used as a reference for the supervisor."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import gcd
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from .net import Marking, PetriNet


# ---------------------------------------------------------------- reachability
@dataclass
class ReachGraph:
    net: PetriNet
    markings: List[Marking]                       # index -> marking
    index: Dict[Marking, int]
    succ: List[List[Tuple[int, int]]]             # index -> [(transition, dst index)]
    parent: List[Optional[Tuple[int, int]]]       # BFS tree: index -> (src index, transition)

    @property
    def size(self) -> int:
        return len(self.markings)


def reachability(net: PetriNet, m0: Optional[Marking] = None,
                 limit: int = 2_000_000) -> ReachGraph:
    m0 = tuple(m0) if m0 is not None else net.initial_marking
    markings = [m0]
    index = {m0: 0}
    succ: List[List[Tuple[int, int]]] = [[]]
    parent: List[Optional[Tuple[int, int]]] = [None]
    queue = deque([0])
    while queue:
        i = queue.popleft()
        for t in net.enabled(markings[i]):
            m2 = net.fire(markings[i], t)
            j = index.get(m2)
            if j is None:
                if len(markings) >= limit:
                    raise RuntimeError("state-space limit exceeded")
                j = len(markings)
                index[m2] = j
                markings.append(m2)
                succ.append([])
                parent.append((i, t))
                queue.append(j)
            succ[i].append((t, j))
    return ReachGraph(net, markings, index, succ, parent)


def trace_to(g: ReachGraph, i: int) -> List[str]:
    """Shortest firing sequence (transition names) from M0 to marking index i."""
    out: List[str] = []
    while g.parent[i] is not None:
        src, t = g.parent[i]
        out.append(g.net.transitions[t].name)
        i = src
    return out[::-1]


def deadlock_indices(g: ReachGraph, final: Callable[[Marking], bool]) -> List[int]:
    """Markings with no enabled transition that are not the completed-batch marking."""
    return [i for i, s in enumerate(g.succ) if not s and not final(g.markings[i])]


def coreachable(g: ReachGraph, goal: Set[int]) -> Set[int]:
    """Indices from which some goal index is reachable."""
    pred: List[List[int]] = [[] for _ in range(g.size)]
    for i, edges in enumerate(g.succ):
        for _, j in edges:
            pred[j].append(i)
    seen = set(goal)
    stack = list(goal)
    while stack:
        j = stack.pop()
        for i in pred[j]:
            if i not in seen:
                seen.add(i)
                stack.append(i)
    return seen


def blocking_indices(g: ReachGraph, final: Callable[[Marking], bool]) -> List[int]:
    """Reachable markings from which the batch can NOT be completed (nonblocking test)."""
    goal = {i for i, m in enumerate(g.markings) if final(m)}
    good = coreachable(g, goal)
    return [i for i in range(g.size) if i not in good]


# ---------------------------------------------------------------- invariants
def _normalise(v: np.ndarray) -> np.ndarray:
    g = 0
    for x in v:
        g = gcd(g, int(abs(x)))
    return v // g if g > 1 else v


def p_invariants(net: PetriNet) -> List[np.ndarray]:
    """Minimal-support semi-positive P-invariants y >= 0 with y^T C = 0 (Farkas algorithm).

    A P-invariant y satisfies y . m = y . m0 for every reachable marking m.
    """
    C = net.C
    P, T = C.shape
    # rows of [C | I]; eliminate columns of C one transition at a time
    rows = [np.concatenate([C[i], np.eye(P, dtype=np.int64)[i]]) for i in range(P)]
    for t in range(T):
        pos = [r for r in rows if r[t] > 0]
        neg = [r for r in rows if r[t] < 0]
        zero = [r for r in rows if r[t] == 0]
        new = []
        for a in pos:
            for b in neg:
                r = a * (-b[t]) + b * a[t]
                new.append(_normalise(r))
        rows = zero + new
        # drop rows whose support strictly contains another row's support (keep minimal)
        supports = [frozenset(np.nonzero(r[T:])[0]) for r in rows]
        keep = []
        for i, s in enumerate(supports):
            if not any(j != i and supports[j] < s for j in range(len(rows))):
                keep.append(i)
        rows = [rows[i] for i in keep]
    invs, seen = [], set()
    for r in rows:
        y = r[T:]
        if (y >= 0).all() and y.any() and not (net.C.T @ y).any():
            key = tuple(int(v) for v in y)
            if key not in seen:
                seen.add(key)
                invs.append(y)
    return invs


def format_invariant(net: PetriNet, y: np.ndarray) -> str:
    lhs = " + ".join((f"{int(c)}*" if c != 1 else "") + net.places[i]
                     for i, c in enumerate(y) if c)
    rhs = int(np.dot(y, np.array(net.m0)))
    return f"{lhs} = {rhs}"


def check_invariants(g: ReachGraph, invs: Sequence[np.ndarray]) -> bool:
    m0 = np.array(g.markings[0])
    arr = np.array(g.markings)
    return all(((arr @ y) == int(y @ m0)).all() for y in invs)


def max_tokens(g: ReachGraph) -> Dict[str, int]:
    arr = np.array(g.markings)
    return {p: int(arr[:, i].max()) for i, p in enumerate(g.net.places)}


# ---------------------------------------------------------------- reference supervisor
def maximally_permissive_safe_set(g: ReachGraph, final: Callable[[Marking], bool]) -> Set[int]:
    """Largest set S of plant markings such that
         (1) the batch completion marking is reachable from every s in S using moves inside S,
         (2) S is closed under *uncontrollable* transitions (a supervisor cannot stop them).
    Computed as a fixpoint on the *unrestricted* plant's reachability graph.  Any supervisor
    that is nonblocking and deadlock-free keeps the plant inside S, so S bounds how permissive
    a supervisor can possibly be.
    """
    net = g.net
    safe = set(range(g.size))
    while True:
        # (2) remove states from which an uncontrollable move leaves the safe set
        changed = True
        while changed:
            changed = False
            for i in list(safe):
                for t, j in g.succ[i]:
                    if not net.transitions[t].controllable and j not in safe:
                        safe.discard(i)
                        changed = True
                        break
        # (1) keep only states that can still complete the batch inside the safe set
        goal = {i for i in safe if final(g.markings[i])}
        pred: Dict[int, List[int]] = {i: [] for i in safe}
        for i in safe:
            for _, j in g.succ[i]:
                if j in safe:
                    pred[j].append(i)
        seen, stack = set(goal), list(goal)
        while stack:
            j = stack.pop()
            for i in pred[j]:
                if i not in seen:
                    seen.add(i)
                    stack.append(i)
        if seen == safe:
            return safe
        safe = seen


def reachable_within(g: ReachGraph, allowed: Set[int]) -> Set[int]:
    """States reachable from M0 using only states in `allowed` (M0 must be in it)."""
    if 0 not in allowed:
        return set()
    seen, stack = {0}, [0]
    while stack:
        i = stack.pop()
        for _, j in g.succ[i]:
            if j in allowed and j not in seen:
                seen.add(j)
                stack.append(j)
    return seen


# ---------------------------------------------------------------- concurrency
def parallel_processing_states(g: ReachGraph) -> int:
    """Reachable markings in which BOTH machines are actively processing at once."""
    ix = g.net.pidx
    m1 = [ix["A_M1_proc"], ix["B_M1_proc"]]
    m2 = [ix["A_M2_proc"], ix["B_M2_proc"]]
    return sum(1 for m in g.markings if any(m[p] for p in m1) and any(m[p] for p in m2))


def max_parts_in_cell(g: ReachGraph) -> int:
    ix = g.net.pidx
    ps = [ix[p] for p in ("A_M1_proc", "A_M1_done", "A_M2_proc", "A_M2_done",
                              "B_M2_proc", "B_M2_done", "B_M1_proc", "B_M1_done")]
    return max(sum(m[p] for p in ps) for m in g.markings)
