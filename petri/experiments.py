"""Timed experiments comparing the three control policies.

Experiment 1 (deterministic grid): whole batch available at t = 0; all 3^4 combinations of
    processing times; both dispatch priorities for the load commands; exact optimum for reference.
Experiment 2 (Monte Carlo): parts arrive at random times in [0, spread]; paired comparison with
    common random numbers (every policy sees the same arrivals, times and priority per seed).
"""
from __future__ import annotations

import itertools
import random
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

from .cell import POLICIES, ProcTimes, build_cell
from .optimal import optimal_makespan
from .timed import Arrival, metrics, simulate

BATCH = (2, 2)
ORDERS = (("A", "B"), ("B", "A"))


def run_one(policy: str, times: ProcTimes, arrivals: Sequence[Arrival], order) -> Dict[str, float]:
    net = build_cell(policy, batch=BATCH, times=times, load_order=order, preload=False)
    res = simulate(net, arrivals, batch=BATCH)
    m = metrics(res, arrivals, times)
    m["end_time"] = float(res.end_time)
    return m


# ------------------------------------------------------------------ experiment 1
def experiment_1(values: Sequence[int] = (2, 4, 8)) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    arrivals: List[Arrival] = [(0, "A_queue", BATCH[0]), (0, "B_queue", BATCH[1])]
    for combo in itertools.product(values, repeat=4):
        times = ProcTimes(*combo)
        opt = optimal_makespan(build_cell("unrestricted", batch=BATCH, times=times, preload=True), BATCH)
        for order in ORDERS:
            for pol in POLICIES:
                m = run_one(pol, times, arrivals, order)
                rows.append(dict(a_m1=combo[0], a_m2=combo[1], b_m2=combo[2], b_m1=combo[3],
                                 order="".join(order), policy=pol, optimal=opt, **m))
    return rows


# ------------------------------------------------------------------ experiment 2
TIME_CLASSES: Dict[str, ProcTimes | None] = {
    "balanced (4,4,4,4)": ProcTimes(4, 4, 4, 4),
    "M2 bottleneck (2,8,8,2)": ProcTimes(2, 8, 8, 2),
    "long first stages (8,2,8,2)": ProcTimes(8, 2, 8, 2),
    "random in {2,4,8}": None,  # drawn per seed
}
SPREADS = (0, 2, 4, 8, 16, 32, 64, 128)


def experiment_2(n_seeds: int = 400, seed: int = 7) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for cname, fixed in TIME_CLASSES.items():
        for spread in SPREADS:
            rng = random.Random(f"{seed}/{cname}/{spread}")
            for k in range(n_seeds):
                times = fixed if fixed is not None else ProcTimes(*(rng.choice((2, 4, 8)) for _ in range(4)))
                arrivals = [(rng.randint(0, spread), p, 1)
                            for p in ("A_queue", "A_queue", "B_queue", "B_queue")]
                order = ORDERS[rng.randint(0, 1)]
                per_policy = {pol: run_one(pol, times, arrivals, order) for pol in POLICIES}
                rows.append(dict(time_class=cname, spread=spread, seed=k, order="".join(order),
                                 **{f"{pol}__{key}": val for pol, m in per_policy.items()
                                    for key, val in m.items()}))
    return rows


# ------------------------------------------------------------------ statistics helpers
def wilson_interval(k: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap_mean_ci(x: Sequence[float], n_boot: int = 2000, seed: int = 11) -> Tuple[float, float, float]:
    a = np.asarray(x, dtype=float)
    if len(a) == 0:
        return (float("nan"),) * 3
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(a), size=(n_boot, len(a)))
    means = a[idx].mean(axis=1)
    return float(a.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))
