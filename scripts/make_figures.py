"""Figures for the technical note -> figures/*.png"""
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, Rectangle

from _common import FIGURES, RESULTS, load_json
from petri.cell import ProcTimes, build_cell
from petri.timed import intervals, simulate

plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "figure.dpi": 150, "savefig.dpi": 200, "savefig.bbox": "tight"})
C_A, C_B, C_M1, C_M2, C_CTRL, C_BAD = "#1b6ca8", "#d96c00", "#3a7d44", "#8a4fa3", "#c0392b", "#c0392b"


# ----------------------------------------------------------------------------- fig 1: the net
def fig_net() -> None:
    fig, ax = plt.subplots(figsize=(15, 6.6))
    ax.set_xlim(-1.2, 16.2); ax.set_ylim(-6.5, 6.0); ax.axis("off"); ax.set_aspect("equal")
    xs = [0, 1.5, 3, 4.5, 6, 7.5, 9, 10.5, 12, 13.5, 15]
    rowA = ["A_queue", "A_load", "A_M1_proc", "A_done_M1", "A_M1_done", "A_xfer",
            "A_M2_proc", "A_done_M2", "A_M2_done", "A_unload", "A_out"]
    rowB = ["B_queue", "B_load", "B_M2_proc", "B_done_M2", "B_M2_done", "B_xfer",
            "B_M1_proc", "B_done_M1", "B_M1_done", "B_unload", "B_out"]
    pos = {}
    for x, a, b in zip(xs, rowA, rowB):
        pos[a], pos[b] = (x, 3.0), (x, -3.0)
    pos.update({"M1_free": (3.0, 0.0), "CTRL": (7.5, 0.0), "M2_free": (12.0, 0.0)})
    transitions = {t for t in rowA + rowB if t.split("_", 1)[1].startswith(("load", "done", "xfer", "unload"))}
    net = build_cell("supervisor")
    tok = dict(zip(net.places, net.m0))
    r = 0.42
    for name, (x, y) in pos.items():
        if name in transitions:
            ctl = name.endswith(("load", "xfer", "unload"))
            ax.add_patch(Rectangle((x - 0.16, y - 0.5), 0.32, 1.0, fc="#222" if ctl else "#999", ec="none", zorder=3))
            ax.text(x, y + (1.45 if y > 0 else -1.45), name, ha="center", va="center", fontsize=8.5,
                    color="#555", zorder=4)
        else:
            col = {"CTRL": C_CTRL, "M1_free": C_M1, "M2_free": C_M2}.get(name, "#222")
            ax.add_patch(Circle((x, y), r, fc="white", ec=col, lw=2.0, zorder=3))
            n = tok.get(name, 0)
            if n:
                ax.text(x, y, str(n) if n > 1 else "●", ha="center", va="center", fontsize=12 if n == 1 else 10, color=col, zorder=4)
            if name in ("M1_free", "M2_free", "CTRL"):
                dx, ha = (-0.62, "right") if name == "M1_free" else (0.62, "left")
                ax.text(x + dx, y, name, ha=ha, va="center", fontsize=9.5, color=col, weight="bold", zorder=4,
                        bbox=dict(fc="white", ec="none", pad=1.0))
            else:
                ax.text(x, y + (0.85 if y > 0 else -0.85), name, ha="center", va="center", fontsize=8.5, zorder=4)

    def arc(src, dst, color="#444", rad=0.0, lw=1.2, ls="-", alpha=1.0):
        (x1, y1), (x2, y2) = pos[src], pos[dst]
        ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=11,
                     connectionstyle=f"arc3,rad={rad}", color=color, lw=lw, ls=ls, alpha=alpha,
                     shrinkA=9 if src not in transitions else 6, shrinkB=9 if dst not in transitions else 6, zorder=2))
    # product flows
    for row in (rowA, rowB):
        for u, v in zip(row[:-1], row[1:]):
            arc(u, v)
    # resource arcs (consume: place -> transition, release: transition -> place)
    for t, rad in (("A_load", 0.15), ("B_xfer", -0.25)):
        arc("M1_free", t, C_M1, rad, ls="--")
    arc("A_xfer", "M1_free", C_M1, 0.22, ls="--")
    arc("B_unload", "M1_free", C_M1, -0.32, ls="--")
    for t, rad in (("B_load", -0.15), ("A_xfer", 0.25)):
        arc("M2_free", t, C_M2, rad, ls="--")
    arc("B_xfer", "M2_free", C_M2, -0.22, ls="--")
    arc("A_unload", "M2_free", C_M2, 0.12, ls="--")
    # supervisor
    for t, rad in (("A_load", 0.12), ("B_load", -0.12)):
        arc("CTRL", t, C_CTRL, rad, lw=1.8)
    for t in ("A_xfer", "B_xfer"):
        arc(t, "CTRL", C_CTRL, 0.0, lw=1.8)
    ax.text(-1.1, 4.9, "Product A:  M1 → M2", color=C_A, fontsize=11, weight="bold")
    ax.text(-1.1, -5.75, "Product B:  M2 → M1", color=C_B, fontsize=11, weight="bold")
    ax.text(16.1, -5.75, "black bar = controllable command  |  grey bar = machine event (timed, uncontrollable)\n"
            "dashed = machine resource  |  red = supervisor  |  completing a stage never frees a machine",
            ha="right", va="center", fontsize=8, color="#333")
    ax.set_title("Supervised manufacturing cell: Petri net with control place CTRL "
                 "(taken by a load, returned by the transfer to the 2nd machine)", fontsize=11, loc="left", pad=2)
    fig.savefig(FIGURES / "fig1_petri_net.png")
    plt.close(fig)


# ----------------------------------------------------------------------------- fig 2: Gantt
def fig_gantt() -> None:
    times = ProcTimes(4, 4, 4, 4)
    arr = [(0, "A_queue", 2), (0, "B_queue", 2)]
    runs = {}
    for pol in ("unrestricted", "one_active", "supervisor"):
        net = build_cell(pol, times=times, preload=False)
        runs[pol] = simulate(net, arr)
    horizon = max(r.end_time for r in runs.values() if not r.deadlock) + 2
    titles = {"unrestricted": "Unrestricted dispatch", "one_active": "Conservative: one active part",
              "supervisor": "Petri-net supervisor (control place)"}
    fig, axes = plt.subplots(3, 1, figsize=(10, 6.4), sharex=True)
    for ax, (pol, res) in zip(axes, runs.items()):
        for mach, prod, kind, s, e in intervals(res, times, horizon=horizon):
            y = 1 if mach == "M1" else 0
            col = C_A if prod == "A" else C_B
            if kind == "proc":
                ax.barh(y, e - s, left=s, height=0.62, color=col, edgecolor="white", lw=1.2)
                ax.text((s + e) / 2, y, prod, ha="center", va="center", color="white", fontsize=9, weight="bold")
            else:
                stuck = (e == horizon and res.deadlock)
                ax.barh(y, e - s, left=s, height=0.62, facecolor="white", edgecolor=C_BAD if stuck else col,
                        hatch="///", lw=1.2)
        ax.set_yticks([0, 1]); ax.set_yticklabels(["M2", "M1"]); ax.set_ylim(-0.6, 1.6)
        status = (f"DEADLOCK at t = {res.end_time}: A holds M1 waiting for M2, B holds M2 waiting for M1"
                  if res.deadlock else f"batch complete at t = {res.end_time}")
        ax.set_title(f"{titles[pol]} — {status}", loc="left", fontsize=10, color=C_BAD if res.deadlock else "black")
        if not res.deadlock:
            ax.axvline(res.end_time, color="#555", lw=0.8, ls=":")
        else:
            ax.text((res.end_time + horizon) / 2, 0.5, "circular wait: finished A needs M2, finished B needs M1\n"
                    "neither machine is ever released", ha="center", va="center", fontsize=9, color=C_BAD,
                    bbox=dict(fc="white", ec=C_BAD, pad=3))
    axes[-1].set_xlabel("time (ticks);  solid = processing, hatched = finished part still holding the machine")
    axes[-1].set_xlim(0, horizon)
    fig.suptitle("Batch 2A + 2B, all processing times 4 ticks", x=0.01, ha="left", fontsize=11, weight="bold")
    fig.tight_layout()
    fig.savefig(FIGURES / "fig2_gantt.png")
    plt.close(fig)


# ----------------------------------------------------------------------------- fig 3: state space
def fig_states() -> None:
    v = load_json("verification.json")
    P = v["policies"]
    names = ["Unrestricted", "One active part", "Control-place\nsupervisor", "Maximally permissive\nreference"]
    safe = [P["unrestricted"]["reachable_markings"] - P["unrestricted"]["markings_that_cannot_complete"],
            P["one_active"]["reachable_markings"], P["supervisor"]["reachable_markings"],
            v["maximally_permissive_reference"]["reachable_markings"]]
    doomed = [P["unrestricted"]["markings_that_cannot_complete"], 0, 0, 0]
    dead = [P["unrestricted"]["deadlocks_with_unfinished_jobs"], 0, 0, 0]
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(4)
    ax.bar(x, safe, color=[C_M1, "#8fbf8f", C_M1, "#555"], label="can still complete the batch")
    ax.bar(x, doomed, bottom=safe, color="#f0a8a0", label="doomed (batch can no longer complete)")
    for i in range(4):
        total = safe[i] + doomed[i]
        ax.text(i, total + 2, f"{total}", ha="center", fontsize=9)
        if doomed[i]:
            ax.text(i, safe[i] + doomed[i] / 2, f"{doomed[i]} doomed\n({dead[i]} are deadlocks)", ha="center",
                    va="center", fontsize=8.5, color="#7a1f17")
    ax.set_xticks(x); ax.set_xticklabels(names, fontsize=9)
    ax.set_ylabel("reachable markings (2A + 2B)"); ax.set_ylim(0, 118)
    ax.legend(frameon=False, loc="upper right", fontsize=8.5)
    ax.set_title("The control place removes every doomed marking and keeps all 81 safe ones", loc="left", fontsize=10.5)
    fig.savefig(FIGURES / "fig3_state_space.png")
    plt.close(fig)


# ----------------------------------------------------------------------------- fig 4: experiment 1
def read_csv(name):
    with open(RESULTS / name) as f:
        return list(csv.DictReader(f))


def fig_exp1() -> None:
    rows = read_csv("exp1_grid.csv")
    sup = [r for r in rows if r["policy"] == "supervisor"]
    one = [r for r in rows if r["policy"] == "one_active"]
    red = np.array([100 * (float(o["makespan"]) - float(s["makespan"])) / float(o["makespan"]) for s, o in zip(sup, one)])
    saving = np.array([float(o["makespan"]) - float(s["makespan"]) for s, o in zip(sup, one)])
    pred = np.array([min(int(s["a_m1"]), int(s["a_m2"])) + min(int(s["b_m2"]), int(s["b_m1"])) for s in sup])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.1))
    ax = axes[0]
    ax.hist(red, bins=np.arange(9, 26.5, 1.0), color=C_M1, edgecolor="white")
    ax.axvline(red.mean(), color="k", ls="--", lw=1)
    ax.text(red.mean() + 0.3, ax.get_ylim()[1] * 0.92, f"mean {red.mean():.1f}%", fontsize=9)
    ax.set_xlabel("makespan reduction of supervisor vs. one-active-part (%)")
    ax.set_ylabel("scenarios (81 time combinations × 2 priorities)")
    ax.set_title("(a) Throughput retained by the interlock", loc="left", fontsize=10)
    ax = axes[1]
    ax.scatter(pred, saving, s=22, color=C_A, alpha=0.6)
    lim = max(pred.max(), saving.max()) + 1
    ax.plot([0, lim], [0, lim], "k--", lw=0.9)
    ax.text(0.5, lim * 0.88, f"all {len(saving)} scenarios on the line\n(max |error| = {np.abs(saving - pred).max():.0f} ticks)", fontsize=9)
    ax.set_xlabel("closed form: min(a₁,a₂) + min(b₂,b₁)  (ticks)")
    ax.set_ylabel("simulated saving (ticks)")
    ax.set_title("(b) Simulation matches the closed-form saving", loc="left", fontsize=10)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig4_exp1_grid.png")
    plt.close(fig)


# ----------------------------------------------------------------------------- fig 5: experiment 2
def fig_exp2() -> None:
    s2 = load_json("experiments_summary.json")["exp2"]
    classes = list(dict.fromkeys(r["time_class"] for r in s2))
    spreads = sorted({r["spread"] for r in s2})
    xs = np.arange(len(spreads))
    cols = ["#1b6ca8", "#d96c00", "#3a7d44", "#8a4fa3"]
    marks, styles = ["o", "s", "^", "D"], ["-", "--", "-", "-"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.2))
    ax = axes[0]
    for c, col, mk, ls in zip(classes, cols, marks, styles):
        rs = [r for r in s2 if r["time_class"] == c]
        p = np.array([r["unrestricted_deadlock_rate"] for r in rs])
        lo = np.array([r["deadlock_ci_lo"] for r in rs]); hi = np.array([r["deadlock_ci_hi"] for r in rs])
        ax.plot(xs, p, marker=mk, ls=ls, color=col, label=c, lw=1.6, ms=4)
        ax.fill_between(xs, lo, hi, color=col, alpha=0.15, lw=0)
    ax.axhline(0, color=C_M1, lw=1.5); ax.text(len(xs) - 1, 0.02, "controlled cells: 0 deadlocks in all runs", ha="right", fontsize=8.5, color=C_M1)
    ax.set_xticks(xs); ax.set_xticklabels(spreads)
    ax.set_xlabel("arrival spread (ticks): each part arrives uniformly in [0, spread]")
    ax.set_ylabel("P(deadlock), unrestricted dispatch"); ax.set_ylim(-0.02, 1.05)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    ax.set_title("(a) How often unrestricted dispatch deadlocks (95% Wilson CI)", loc="left", fontsize=10)
    ax = axes[1]
    for c, col, mk, ls in zip(classes, cols, marks, styles):
        rs = [r for r in s2 if r["time_class"] == c]
        ax.plot(xs, [r["saving_pct"] for r in rs], marker=mk, ls=ls, color=col, label=c, lw=1.6, ms=5)
    ax.text(0.2, 3.2, "M2-bottleneck and long-first-stage classes\ncoincide (both save 4 of 40 ticks)", fontsize=8, color="#555")
    ax.set_xticks(xs); ax.set_xticklabels(spreads)
    ax.set_xlabel("arrival spread (ticks)"); ax.set_ylabel("supervisor makespan saving vs one-active (%)")
    ax.set_title("(b) Throughput benefit of the interlock shrinks as arrivals spread out", loc="left", fontsize=10)
    ax.set_ylim(0, None)
    fig.tight_layout()
    fig.savefig(FIGURES / "fig5_exp2_montecarlo.png")
    plt.close(fig)


if __name__ == "__main__":
    fig_net(); fig_gantt(); fig_states(); fig_exp1(); fig_exp2()
    print("figures written to", FIGURES)
