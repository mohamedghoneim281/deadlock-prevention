"""Exhaustive verification of the three policies (untimed)."""
from __future__ import annotations

from typing import Dict, List, Set, Tuple

from .analysis import (blocking_indices, check_invariants, deadlock_indices, format_invariant,
                       max_parts_in_cell, max_tokens, maximally_permissive_safe_set,
                       p_invariants, parallel_processing_states, reachability,
                       reachable_within, trace_to)
from .cell import POLICIES, build_cell, is_final, project_base
from .net import PetriNet


def projected_edges(net: PetriNet, g) -> Set[Tuple[tuple, str, tuple]]:
    return {(project_base(net, g.markings[i]), net.transitions[t].name, project_base(net, g.markings[j]))
            for i, edges in enumerate(g.succ) for t, j in edges}


def verify_policy(policy: str, batch=(2, 2)) -> Dict[str, object]:
    net = build_cell(policy, batch=batch)
    g = reachability(net)
    fin = lambda m: is_final(net, m, batch)
    dl = deadlock_indices(g, fin)
    bl = blocking_indices(g, fin)
    invs = p_invariants(net)
    out: Dict[str, object] = dict(
        policy=policy, batch=list(batch), places=len(net.places), transitions=len(net.transitions),
        reachable_markings=g.size, edges=sum(len(s) for s in g.succ),
        deadlocks_with_unfinished_jobs=len(dl),
        markings_that_cannot_complete=len(bl),
        completion_marking_reachable=any(fin(m) for m in g.markings),
        every_marking_can_complete=len(bl) == 0,
        p_invariants=[format_invariant(net, y) for y in invs],
        invariants_hold_on_all_markings=check_invariants(g, invs),
        max_tokens_per_place=max_tokens(g),
        one_bounded_machine_places=all(v <= 1 for p, v in max_tokens(g).items()
                                       if p.startswith(("M1", "M2", "CTRL")) or "_proc" in p or "_done" in p),
        markings_with_both_machines_processing=parallel_processing_states(g),
        max_parts_in_cell=max_parts_in_cell(g),
    )
    if dl:
        out["shortest_deadlock_trace"] = trace_to(g, dl[0])
        out["deadlock_markings"] = [net.marking_dict(g.markings[i]) for i in dl]
    return out


def verify_all(batch=(2, 2)) -> Dict[str, object]:
    """All policies + comparison with the maximally permissive reference supervisor."""
    res: Dict[str, object] = {"policies": {}}
    for pol in POLICIES:
        res["policies"][pol] = verify_policy(pol, batch)

    plant = build_cell("unrestricted", batch=batch)
    gu = reachability(plant)
    fin = lambda m: is_final(plant, m, batch)
    safe = maximally_permissive_safe_set(gu, fin)
    mp_reach = reachable_within(gu, safe)
    mp_states = {gu.markings[i] for i in mp_reach}
    mp_edges = {(gu.markings[i], plant.transitions[t].name, gu.markings[j])
                for i in mp_reach for t, j in gu.succ[i] if j in safe}
    ref: Dict[str, object] = dict(reachable_markings=len(mp_states), edges=len(mp_edges))
    for pol in ("one_active", "supervisor"):
        net = build_cell(pol, batch=batch)
        g = reachability(net)
        states = {project_base(net, m) for m in g.markings}
        edges = projected_edges(net, g)
        ref[pol] = dict(
            states_subset_of_maximal=states <= mp_states,
            safe_states_given_up=len(mp_states - states),
            edges_subset_of_maximal=edges <= mp_edges,
            safe_edges_given_up=len(mp_edges - edges),
            equals_maximally_permissive=(states == mp_states and edges == mp_edges),
        )
    res["maximally_permissive_reference"] = ref
    # the "point of no return": markings that are doomed but not yet deadlocked
    bl = blocking_indices(gu, fin)
    dl = deadlock_indices(gu, fin)
    res["unrestricted_doomed_but_not_yet_deadlocked"] = len(bl) - len(dl)
    return res


def scaling_table(max_n: int = 4) -> List[Dict[str, object]]:
    """How the state space and the supervisor's optimality behave for larger batches (n A + n B)."""
    rows = []
    for n in range(1, max_n + 1):
        r = verify_all((n, n))
        row: Dict[str, object] = {"batch": f"{n}A+{n}B"}
        for pol in POLICIES:
            p = r["policies"][pol]
            row[f"{pol}_markings"] = p["reachable_markings"]
            row[f"{pol}_deadlocks"] = p["deadlocks_with_unfinished_jobs"]
        row["maximal_markings"] = r["maximally_permissive_reference"]["reachable_markings"]
        row["supervisor_is_maximal"] = r["maximally_permissive_reference"]["supervisor"]["equals_maximally_permissive"]
        row["one_active_gives_up"] = r["maximally_permissive_reference"]["one_active"]["safe_states_given_up"]
        rows.append(row)
    return rows
