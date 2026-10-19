import itertools

import pytest

from petri.cell import POLICIES, ProcTimes, build_cell
from petri.experiments import run_one
from petri.optimal import optimal_makespan
from petri.timed import intervals, metrics, simulate

BATCH0 = [(0, "A_queue", 2), (0, "B_queue", 2)]
ORDERS = (("A", "B"), ("B", "A"))


def run(policy, times, order=("A", "B"), arrivals=BATCH0):
    net = build_cell(policy, times=times, load_order=order, preload=False)
    return net, simulate(net, arrivals)


def test_hand_computed_case_all_ones():
    ones = ProcTimes(1, 1, 1, 1)
    _, un = run("unrestricted", ones)
    assert un.deadlock and un.end_time == 1
    assert run("one_active", ones)[1].end_time == 8
    assert run("supervisor", ones)[1].end_time == 6


def test_deterministic():
    a = run("supervisor", ProcTimes(3, 5, 2, 7))[1].log
    b = run("supervisor", ProcTimes(3, 5, 2, 7))[1].log
    assert a == b


@pytest.mark.parametrize("combo", list(itertools.product((1, 3, 8), repeat=4)))
@pytest.mark.parametrize("order", ORDERS)
def test_closed_form_makespans(combo, order):
    a1, a2, b2, b1 = combo
    times = ProcTimes(*combo)
    # one active part: every part does both stages alone
    assert run("one_active", times, order)[1].end_time == 2 * (a1 + a2 + b2 + b1)
    # supervisor: parts of one product pipeline through the two machines, products alternate
    expected = max(2 * a1 + a2, a1 + 2 * a2) + max(2 * b2 + b1, b2 + 2 * b1)
    assert run("supervisor", times, order)[1].end_time == expected


def test_unrestricted_deadlocks_at_time_zero_batch_for_every_time_combo():
    for combo in itertools.product((1, 4, 9), repeat=4):
        assert run("unrestricted", ProcTimes(*combo))[1].deadlock


def test_optimum_is_a_lower_bound_and_supervisor_reaches_it():
    for combo in itertools.product((2, 5), repeat=4):
        times = ProcTimes(*combo)
        opt = optimal_makespan(build_cell("unrestricted", times=times))
        for order in ORDERS:
            for pol in ("one_active", "supervisor"):
                assert run(pol, times, order)[1].end_time >= opt
            assert run("supervisor", times, order)[1].end_time == opt


def test_no_deadlock_when_products_arrive_far_apart():
    arr = [(0, "A_queue", 2), (1000, "B_queue", 2)]
    net, res = run("unrestricted", ProcTimes(4, 4, 4, 4), arrivals=arr)
    assert not res.deadlock


def test_late_second_product_can_still_deadlock_the_unrestricted_cell():
    # B arrives while A is still in its first stage -> classic circular wait
    arr = [(0, "A_queue", 2), (2, "B_queue", 2)]
    assert run("unrestricted", ProcTimes(4, 4, 4, 4), arrivals=arr)[1].deadlock
    assert not run("supervisor", ProcTimes(4, 4, 4, 4), arrivals=arr)[1].deadlock


def test_metrics_and_gantt_are_consistent():
    times = ProcTimes(1, 1, 1, 1)
    net, res = run("supervisor", times)
    m = metrics(res, BATCH0, times)
    assert m["makespan"] == 6 and m["util_m1"] == pytest.approx(4 / 6) and m["blocked_m1"] == 0
    busy = sum(e - s for mach, _, k, s, e in intervals(res, times) if k == "proc")
    assert busy == 8   # 4 operations on each machine, 1 tick each
    # the deadlocked unrestricted cell shows both machines held by finished parts
    _, un = run("unrestricted", times)
    holds = [iv for iv in intervals(un, times, horizon=6) if iv[2] == "hold"]
    assert {h[0] for h in holds} == {"M1", "M2"} and all(h[4] == 6 for h in holds)


def test_no_deadlock_under_control_across_random_scenarios():
    import random
    rng = random.Random(1)
    for _ in range(300):
        times = ProcTimes(*(rng.randint(1, 9) for _ in range(4)))
        arr = [(rng.randint(0, 40), p, 1) for p in ("A_queue", "A_queue", "B_queue", "B_queue")]
        order = ORDERS[rng.randint(0, 1)]
        for pol in ("one_active", "supervisor"):
            m = run_one(pol, times, arr, order)
            assert m["deadlock"] == 0.0
        sup = run_one("supervisor", times, arr, order)["makespan"]
        one = run_one("one_active", times, arr, order)["makespan"]
        assert sup <= one
