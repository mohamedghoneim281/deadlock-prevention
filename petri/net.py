"""Core place/transition Petri net.

A net is (P, T, Pre, Post, M0).  Pre[p, t] / Post[p, t] are the arc weights,
the incidence matrix is C = Post - Pre, and firing t in marking m gives
m' = m + C[:, t] provided m >= Pre[:, t] (the enabling condition).

Each transition additionally carries
  * ``controllable``: whether a supervisor may disable it (start / transfer
    commands are controllable; processing-completion events are not), and
  * ``delay``: integer ticks.  0 = immediate (fired by the dispatcher),
    > 0 = timed (fires ``delay`` ticks after it becomes enabled).

The *order* in which transitions are added is the dispatch priority order.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

import numpy as np

Marking = Tuple[int, ...]


@dataclass(frozen=True)
class Transition:
    name: str
    controllable: bool
    delay: int  # ticks; 0 => immediate


class PetriNet:
    def __init__(self) -> None:
        self.places: List[str] = []
        self.m0: List[int] = []
        self.transitions: List[Transition] = []
        self._pre: List[Dict[str, int]] = []
        self._post: List[Dict[str, int]] = []
        self._frozen = False

    # ------------------------------------------------------------ building
    def add_place(self, name: str, tokens: int = 0) -> None:
        assert not self._frozen, "net already finalised"
        assert name not in self.places, f"duplicate place {name}"
        self.places.append(name)
        self.m0.append(int(tokens))

    def add_transition(self, name: str, pre: Dict[str, int], post: Dict[str, int],
                       controllable: bool, delay: int = 0) -> None:
        assert not self._frozen, "net already finalised"
        assert name not in [t.name for t in self.transitions], f"duplicate transition {name}"
        assert delay >= 0
        for p in list(pre) + list(post):
            assert p in self.places, f"unknown place {p} in transition {name}"
        self.transitions.append(Transition(name, controllable, int(delay)))
        self._pre.append(dict(pre))
        self._post.append(dict(post))

    def finalize(self) -> "PetriNet":
        P, T = len(self.places), len(self.transitions)
        pidx = {p: i for i, p in enumerate(self.places)}
        self.pre = np.zeros((P, T), dtype=np.int64)
        self.post = np.zeros((P, T), dtype=np.int64)
        for t in range(T):
            for p, w in self._pre[t].items():
                self.pre[pidx[p], t] = w
            for p, w in self._post[t].items():
                self.post[pidx[p], t] = w
        self.C = self.post - self.pre
        self.pidx = pidx
        self.tidx = {t.name: i for i, t in enumerate(self.transitions)}
        # per-transition sparse views for fast enabling/firing in pure Python
        self._pre_sp = [[(pidx[p], w) for p, w in d.items()] for d in self._pre]
        self._c_sp = [
            [(i, int(self.C[i, t])) for i in range(P) if self.C[i, t] != 0] for t in range(T)
        ]
        self._frozen = True
        return self

    # ------------------------------------------------------------ semantics
    @property
    def initial_marking(self) -> Marking:
        return tuple(self.m0)

    def is_enabled(self, m: Sequence[int], t: int) -> bool:
        for p, w in self._pre_sp[t]:
            if m[p] < w:
                return False
        return True

    def enabled(self, m: Sequence[int]) -> List[int]:
        return [t for t in range(len(self.transitions)) if self.is_enabled(m, t)]

    def fire(self, m: Sequence[int], t: int) -> Marking:
        assert self.is_enabled(m, t), f"{self.transitions[t].name} not enabled in {m}"
        out = list(m)
        for p, dw in self._c_sp[t]:
            out[p] += dw
        return tuple(out)

    def marking_dict(self, m: Sequence[int]) -> Dict[str, int]:
        return {p: v for p, v in zip(self.places, m) if v}

    def with_initial_marking(self, tokens: Dict[str, int]) -> "PetriNet":
        """Return a copy whose initial marking is overridden for the named places."""
        other = copy.copy(self)
        other.m0 = list(self.m0)
        for p, v in tokens.items():
            other.m0[self.pidx[p]] = int(v)
        return other

    # ------------------------------------------------------------ export
    def to_text(self) -> str:
        """Plain-text format read by the C++ engine (see cpp/petri_net.hpp)."""
        lines = ["# place <name> <initial tokens>"]
        for p, v in zip(self.places, self.m0):
            lines.append(f"place {p} {v}")
        lines.append("# transition <name> <controllable 0|1> <delay ticks>; file order = dispatch priority")
        for t in self.transitions:
            lines.append(f"transition {t.name} {int(t.controllable)} {t.delay}")
        lines.append("# pre|post <transition> <place> <weight>")
        for i, t in enumerate(self.transitions):
            for p, w in self._pre[i].items():
                lines.append(f"pre {t.name} {p} {w}")
            for p, w in self._post[i].items():
                lines.append(f"post {t.name} {p} {w}")
        return "\n".join(lines) + "\n"
