import itertools

import numpy as np
import pytest

from petri.analysis import (blocking_indices, check_invariants, deadlock_indices, max_tokens,
                            p_invariants, reachability, trace_to)
from petri.cell import POLICIES, build_cell, is_final
from petri.net import PetriNet
from petri.verify import scaling_table, verify_all


def test_incidence_is_post_minus_pre_and_firing_follows_state_equation():
    net = build_cell("supervisor")
    assert (net.C == net.post - net.pre).all()
    m = net.initial_marking
    t = net.tidx["A_load"]
    m2 = net.fire(m, t)
    assert np.array_equal(np.array(m2), np.array(m) + net.C[:, t])
    assert m2[net.pidx["CTRL"]] == 0 and m2[net.pidx["M1_free"]] == 0 and m2[net.pidx["A_M1_proc"]] == 1


def test_firing_a_disabled_transition_is_rejected():
    net = build_cell("unrestricted")
    with pytest.raises(AssertionError):
        net.fire(net.initial_marking, net.tidx["A_xfer"])


def test_completing_processing_never_releases_a_machine():
    """Core modelling rule: only xfer/unload (never *_done_*) put a token back on M1_free/M2_free."""
    net = build_cell("unrestricted")
    for t in net.transitions:
        if t.name.startswith(("A_done", "B_done")):
            col = net.C[:, net.tidx[t.name]]
            assert col[net.pidx["M1_free"]] == 0 and col[net.pidx["M2_free"]] == 0


# ---- the numbers claimed for the 2A+2B cell
@pytest.mark.parametrize("policy,markings,deadlocks", [
    ("unrestricted", 97, 4), ("one_active", 57, 0), ("supervisor", 81, 0)])
def test_reachable_markings_and_deadlocks(policy, markings, deadlocks):
    net = build_cell(policy)
    g = reachability(net)
    assert g.size == markings
    assert len(deadlock_indices(g, lambda m: is_final(net, m))) == deadlocks


def test_shortest_deadlock_trace_is_valid_and_terminal():
    net = build_cell("unrestricted")
    g = reachability(net)
    dl = deadlock_indices(g, lambda m: is_final(net, m))
    tr = trace_to(g, dl[0])
    assert tr == ["A_load", "B_load", "A_done_M1", "B_done_M2"]
    m = net.initial_marking
    for name in tr:
        m = net.fire(m, net.tidx[name])
    assert net.enabled(m) == [] and not is_final(net, m)
    assert m[net.pidx["A_M1_done"]] == 1 and m[net.pidx["B_M2_done"]] == 1


def test_unrestricted_has_more_doomed_markings_than_deadlocks():
    net = build_cell("unrestricted")
    g = reachability(net)
    fin = lambda m: is_final(net, m)
    assert len(blocking_indices(g, fin)) == 16 and len(deadlock_indices(g, fin)) == 4


@pytest.mark.parametrize("policy", ["one_active", "supervisor"])
def test_controlled_nets_are_deadlock_free_and_nonblocking(policy):
    net = build_cell(policy)
    g = reachability(net)
    fin = lambda m: is_final(net, m)
    assert deadlock_indices(g, fin) == [] and blocking_indices(g, fin) == []


@pytest.mark.parametrize("policy", POLICIES)
def test_p_invariants_valid_and_hold(policy):
    net = build_cell(policy)
    invs = p_invariants(net)
    assert len(invs) >= 4
    for y in invs:
        assert (y >= 0).all() and not (net.C.T @ y).any()
    assert check_invariants(reachability(net), invs)


def test_machine_conservation_invariants_are_found():
    net = build_cell("supervisor")
    found = {frozenset(net.places[i] for i in np.nonzero(y)[0]) for y in p_invariants(net)}
    m1 = {"M1_free", "A_M1_proc", "A_M1_done", "B_M1_proc", "B_M1_done"}
    m2 = {"M2_free", "A_M2_proc", "A_M2_done", "B_M2_proc", "B_M2_done"}
    assert m1 in found and m2 in found
    assert {"CTRL", "A_M1_proc", "A_M1_done", "B_M2_proc", "B_M2_done"} in found  # the interlock


@pytest.mark.parametrize("policy", POLICIES)
def test_one_bounded_machine_resources(policy):
    mt = max_tokens(reachability(build_cell(policy)))
    for p in ("M1_free", "M2_free", "A_M1_proc", "A_M1_done", "A_M2_proc", "A_M2_done",
              "B_M2_proc", "B_M2_done", "B_M1_proc", "B_M1_done"):
        assert mt[p] == 1
    if policy != "unrestricted":
        assert mt["CTRL"] == 1


def test_supervisor_is_maximally_permissive_and_one_active_is_not():
    ref = verify_all()["maximally_permissive_reference"]
    assert ref["reachable_markings"] == 81
    assert ref["supervisor"]["equals_maximally_permissive"]
    assert ref["one_active"]["states_subset_of_maximal"] and ref["one_active"]["safe_states_given_up"] == 24


def test_supervisor_stays_maximal_for_larger_batches():
    for row in scaling_table(4):
        assert row["supervisor_deadlocks"] == 0 and row["one_active_deadlocks"] == 0
        assert row["unrestricted_deadlocks"] == int(row["batch"][0]) ** 2
        assert row["supervisor_is_maximal"]


# ---- mutation test: the checker must catch a WRONG supervisor, otherwise it proves nothing
def _flawed_supervisor() -> PetriNet:
    """Permission token returned when the first stage *finishes* instead of when the part has
    moved on.  The part still holds its first machine, so the opposite product can load."""
    base = build_cell("supervisor")
    net = PetriNet()
    for p, v in zip(base.places, base.m0):
        net.add_place(p, v)
    for i, t in enumerate(base.transitions):
        pre = {base.places[p]: int(base.pre[p, i]) for p in range(len(base.places)) if base.pre[p, i]}
        post = {base.places[p]: int(base.post[p, i]) for p in range(len(base.places)) if base.post[p, i]}
        if t.name in ("A_xfer", "B_xfer"):
            post.pop("CTRL")
        if t.name in ("A_done_M1", "B_done_M2"):
            post["CTRL"] = 1
        net.add_transition(t.name, pre, post, t.controllable, t.delay)
    return net.finalize()


def test_checker_detects_a_flawed_supervisor():
    net = _flawed_supervisor()
    g = reachability(net)
    dl = deadlock_indices(g, lambda m: is_final(net, m))
    assert dl, "the flawed interlock should deadlock and the checker must say so"
    assert len(trace_to(g, dl[0])) > 0
