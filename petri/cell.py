"""The two-machine manufacturing cell and its three control policies.

Cell
----
* Machines M1 and M2, capacity one part each, no intermediate buffer.
* Product A needs M1 then M2.  Product B needs M2 then M1.
* Completing processing NEVER frees a machine.  A finished part keeps holding its
  machine until an explicit command moves it on: ``xfer`` (to the second machine,
  atomic, only if that machine is free) or ``unload`` (to the output, always possible).

Places (tokens)
---------------
  A_queue, B_queue     waiting parts
  M1_free, M2_free     machine-availability resources
  A_M1_proc            A being processed on M1          (holds M1)
  A_M1_done            A finished on M1, waiting for M2 (still holds M1)
  A_M2_proc            A being processed on M2          (holds M2)
  A_M2_done            A finished on M2, waiting for unload (still holds M2)
  B_M2_proc / B_M2_done / B_M1_proc / B_M1_done   symmetric for product B
  A_out, B_out         finished parts
  CTRL                 control place (supervised policies only)

Transitions
-----------
  controllable commands (dispatcher / supervisor may block them):
        A_load, A_xfer, A_unload, B_load, B_xfer, B_unload
  uncontrollable machine events (timed = processing time):
        A_done_M1, A_done_M2, B_done_M2, B_done_M1

Policies
--------
  unrestricted : no control place; every enabled start command may fire.
  one_active   : CTRL has one token, taken by a load and returned only by the final
                 *unload* (conservative: one part in the cell at a time).
  supervisor   : CTRL has one token, taken by a load and returned by the
                 *transfer* to the second machine.  This forbids an A and a B from
                 simultaneously holding their (opposite) first machines.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from .net import Marking, PetriNet

POLICIES = ("unrestricted", "one_active", "supervisor")

BASE_PLACES = (
    "A_queue", "B_queue", "M1_free", "M2_free",
    "A_M1_proc", "A_M1_done", "A_M2_proc", "A_M2_done", "A_out",
    "B_M2_proc", "B_M2_done", "B_M1_proc", "B_M1_done", "B_out",
)
CTRL = "CTRL"


@dataclass(frozen=True)
class ProcTimes:
    """Processing times in integer ticks (>= 1)."""
    a_m1: int = 4   # product A, first stage, on M1
    a_m2: int = 4   # product A, second stage, on M2
    b_m2: int = 4   # product B, first stage, on M2
    b_m1: int = 4   # product B, second stage, on M1

    def __post_init__(self) -> None:
        for v in (self.a_m1, self.a_m2, self.b_m2, self.b_m1):
            if v < 1:
                raise ValueError("processing times must be >= 1 tick")


def build_cell(policy: str = "unrestricted",
               batch: Tuple[int, int] = (2, 2),
               times: ProcTimes = ProcTimes(),
               load_order: Tuple[str, str] = ("A", "B"),
               preload: bool = True) -> PetriNet:
    """Build the cell net.

    preload=True  : the whole batch is in the queues at t=0 (untimed analysis).
    preload=False : queues start empty; parts arrive through external events.
    load_order    : dispatch priority between the A and B load commands.
    Dispatch priority: unloads, then transfers, then loads ("finish what you started").
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    assert sorted(load_order) == ["A", "B"]
    n_a, n_b = batch
    net = PetriNet()
    q = {"A_queue": n_a if preload else 0, "B_queue": n_b if preload else 0}
    for p in BASE_PLACES:
        tokens = {**q, "M1_free": 1, "M2_free": 1}.get(p, 0)
        net.add_place(p, tokens)
    controlled = policy != "unrestricted"
    if controlled:
        net.add_place(CTRL, 1)

    def ctl(take: bool = False, give: bool = False):
        pre, post = {}, {}
        if controlled and take:
            pre[CTRL] = 1
        if controlled and give:
            post[CTRL] = 1
        return pre, post

    # which transitions touch the control place under each policy
    take_on_load = controlled
    give_on_xfer = policy == "supervisor"
    give_on_unload = policy == "one_active"

    # ---- immediate / controllable commands (dispatch priority: unloads, transfers, loads)
    def add_xfer(prod: str) -> None:
        if prod == "A":
            pre = {"A_M1_done": 1, "M2_free": 1}
            post = {"A_M2_proc": 1, "M1_free": 1}
            name = "A_xfer"
        else:
            pre = {"B_M2_done": 1, "M1_free": 1}
            post = {"B_M1_proc": 1, "M2_free": 1}
            name = "B_xfer"
        cpre, cpost = ctl(give=give_on_xfer)
        pre.update(cpre)
        post.update(cpost)
        net.add_transition(name, pre, post, controllable=True, delay=0)

    def add_load(prod: str) -> None:
        if prod == "A":
            pre = {"A_queue": 1, "M1_free": 1}
            post = {"A_M1_proc": 1}
            name = "A_load"
        else:
            pre = {"B_queue": 1, "M2_free": 1}
            post = {"B_M2_proc": 1}
            name = "B_load"
        cpre, cpost = ctl(take=take_on_load)
        pre.update(cpre)
        post.update(cpost)
        net.add_transition(name, pre, post, controllable=True, delay=0)

    def add_unload(prod: str) -> None:
        if prod == "A":
            pre, post, name = {"A_M2_done": 1}, {"M2_free": 1, "A_out": 1}, "A_unload"
        else:
            pre, post, name = {"B_M1_done": 1}, {"M1_free": 1, "B_out": 1}, "B_unload"
        cpre, cpost = ctl(give=give_on_unload)
        pre.update(cpre)
        post.update(cpost)
        net.add_transition(name, pre, post, controllable=True, delay=0)

    add_unload("A")
    add_unload("B")
    add_xfer("A")
    add_xfer("B")
    for prod in load_order:
        add_load(prod)

    # ---- uncontrollable machine events (timed); none of them releases a machine
    net.add_transition("A_done_M1", {"A_M1_proc": 1}, {"A_M1_done": 1},
                       controllable=False, delay=times.a_m1)
    net.add_transition("A_done_M2", {"A_M2_proc": 1}, {"A_M2_done": 1},
                       controllable=False, delay=times.a_m2)
    net.add_transition("B_done_M2", {"B_M2_proc": 1}, {"B_M2_done": 1},
                       controllable=False, delay=times.b_m2)
    net.add_transition("B_done_M1", {"B_M1_proc": 1}, {"B_M1_done": 1},
                       controllable=False, delay=times.b_m1)
    return net.finalize()


def is_final(net: PetriNet, m: Marking, batch: Tuple[int, int] = (2, 2)) -> bool:
    """Batch complete: every part is in an output place and nothing is queued."""
    return m[net.pidx["A_out"]] == batch[0] and m[net.pidx["B_out"]] == batch[1]


def project_base(net: PetriNet, m: Marking) -> Marking:
    """Drop the control place so markings of different policies are comparable."""
    return tuple(m[net.pidx[p]] for p in BASE_PLACES)
