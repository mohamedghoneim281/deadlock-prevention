"""Timed experiments -> results/exp1_grid.csv, exp2_montecarlo.csv, experiments_summary.json"""
import csv

import numpy as np

from _common import RESULTS, save_json
from petri.experiments import (SPREADS, TIME_CLASSES, bootstrap_mean_ci, experiment_1, experiment_2,
                               wilson_interval)


def write_csv(name, rows):
    with open(RESULTS / name, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def summarise_exp1(rows):
    by = lambda pol: [r for r in rows if r["policy"] == pol]
    unr, one, sup = by("unrestricted"), by("one_active"), by("supervisor")
    ok = lambda rs: [r for r in rs if not r["deadlock"]]
    red = np.array([(o["makespan"] - s["makespan"]) / o["makespan"] for s, o in zip(sup, one)])
    abs_red = np.array([o["makespan"] - s["makespan"] for s, o in zip(sup, one)])
    # closed form: saving = min(a_m1, a_m2) + min(b_m2, b_m1)
    pred = np.array([min(s["a_m1"], s["a_m2"]) + min(s["b_m2"], s["b_m1"]) for s in sup])
    gap = np.array([(s["makespan"] - s["optimal"]) / s["optimal"] for s in sup])
    mean = lambda rs, k: float(np.mean([r[k] for r in rs]))
    return dict(
        runs_per_policy=len(sup),
        unrestricted_deadlocked=int(sum(r["deadlock"] for r in unr)),
        one_active_deadlocked=int(sum(r["deadlock"] for r in one)),
        supervisor_deadlocked=int(sum(r["deadlock"] for r in sup)),
        supervisor_vs_one_active=dict(
            mean_reduction_pct=100 * float(red.mean()), min_reduction_pct=100 * float(red.min()),
            max_reduction_pct=100 * float(red.max()), strictly_faster_in=int((red > 0).sum()),
            never_slower=bool((red >= 0).all()),
            closed_form_saving_matches_all=bool((abs_red == pred).all())),
        supervisor_vs_optimal=dict(
            mean_gap_pct=100 * float(gap.mean()), max_gap_pct=100 * float(gap.max()),
            runs_at_optimum=int((gap == 0).sum()), runs=len(gap)),
        mean_utilisation=dict(
            one_active=dict(M1=mean(ok(one), "util_m1"), M2=mean(ok(one), "util_m2")),
            supervisor=dict(M1=mean(ok(sup), "util_m1"), M2=mean(ok(sup), "util_m2"))),
        mean_queue_wait=dict(one_active=mean(ok(one), "mean_wait"), supervisor=mean(ok(sup), "mean_wait")),
        mean_flow_time=dict(one_active=mean(ok(one), "mean_flow"), supervisor=mean(ok(sup), "mean_flow")),
        mean_blocking_ticks=dict(one_active=mean(ok(one), "blocked_m1") + mean(ok(one), "blocked_m2"),
                                 supervisor=mean(ok(sup), "blocked_m1") + mean(ok(sup), "blocked_m2")),
    )


def summarise_exp2(rows):
    out = []
    for cname in TIME_CLASSES:
        for spread in SPREADS:
            rs = [r for r in rows if r["time_class"] == cname and r["spread"] == spread]
            n = len(rs)
            dl = sum(int(r["unrestricted__deadlock"]) for r in rs)
            lo, hi = wilson_interval(dl, n)
            sup = np.array([r["supervisor__makespan"] for r in rs])
            one = np.array([r["one_active__makespan"] for r in rs])
            unr_ok = [r for r in rs if not r["unrestricted__deadlock"]]
            diff = one - sup                                    # paired, same scenario
            d_mean, d_lo, d_hi = bootstrap_mean_ci(diff)
            pct = float(100 * np.mean(diff / one))
            # price of safety on scenarios where the unrestricted cell happens to survive
            price = [r["supervisor__makespan"] - r["unrestricted__makespan"] for r in unr_ok]
            out.append(dict(
                time_class=cname, spread=spread, n=n,
                unrestricted_deadlock_rate=dl / n, deadlock_ci_lo=lo, deadlock_ci_hi=hi,
                controlled_deadlocks=int(sum(int(r["one_active__deadlock"]) + int(r["supervisor__deadlock"]) for r in rs)),
                supervisor_mean_makespan=float(sup.mean()), one_active_mean_makespan=float(one.mean()),
                unrestricted_mean_makespan_completed=(float(np.mean([r["unrestricted__makespan"] for r in unr_ok])) if unr_ok else None),
                saving_vs_one_active_mean=d_mean, saving_ci_lo=d_lo, saving_ci_hi=d_hi, saving_pct=pct,
                supervisor_never_slower_than_one_active=bool((diff >= 0).all()),
                price_of_safety_mean=(float(np.mean(price)) if price else None),
                price_of_safety_n=len(price),
            ))
    return out


def main() -> None:
    r1 = experiment_1()
    write_csv("exp1_grid.csv", r1)
    s1 = summarise_exp1(r1)
    r2 = experiment_2(n_seeds=500)
    write_csv("exp2_montecarlo.csv", r2)
    s2 = summarise_exp2(r2)
    save_json("experiments_summary.json", dict(exp1=s1, exp2=s2))
    e = s1["supervisor_vs_one_active"]
    print(f"Exp1: unrestricted deadlocked {s1['unrestricted_deadlocked']}/{s1['runs_per_policy']}; "
          f"supervisor saves {e['mean_reduction_pct']:.1f}% (range {e['min_reduction_pct']:.1f}-{e['max_reduction_pct']:.1f}%) "
          f"vs one-active; closed form matches: {e['closed_form_saving_matches_all']}; "
          f"gap to optimum: {s1['supervisor_vs_optimal']['max_gap_pct']:.2f}% max")
    for row in s2:
        if row["time_class"].startswith("balanced"):
            print(f"Exp2 balanced spread={row['spread']:2d}: P(deadlock)={row['unrestricted_deadlock_rate']:.2f} "
                  f"sup={row['supervisor_mean_makespan']:.1f} one-active={row['one_active_mean_makespan']:.1f}")


if __name__ == "__main__":
    main()
