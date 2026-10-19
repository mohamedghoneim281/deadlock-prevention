"""Exhaustive untimed verification -> results/verification.json, scaling.csv, matrices.txt"""
import csv

from _common import RESULTS, save_json
from petri.cell import build_cell
from petri.verify import scaling_table, verify_all


def matrix_text(net) -> str:
    """Pre, Post and incidence matrices with row/column labels (the model's 'matrices')."""
    w = max(len(p) for p in net.places) + 1
    cols = [t.name for t in net.transitions]
    cw = max(len(c) for c in cols) + 1

    def block(title, M):
        lines = [title, " " * w + "".join(c.rjust(cw) for c in cols)]
        for i, p in enumerate(net.places):
            lines.append(p.ljust(w) + "".join(str(int(M[i, j])).rjust(cw) for j in range(M.shape[1])))
        return "\n".join(lines)

    return "\n\n".join([block("Pre  (input arcs)", net.pre), block("Post (output arcs)", net.post),
                        block("C = Post - Pre (incidence)", net.C)])


def main() -> None:
    res = verify_all((2, 2))
    save_json("verification.json", res)
    rows = scaling_table(4)
    with open(RESULTS / "scaling.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    save_json("scaling.json", rows)
    sup = build_cell("supervisor")
    (RESULTS / "matrices_supervisor.txt").write_text(
        "Supervised cell (control place CTRL), batch 2A+2B\n\n" + matrix_text(sup) + "\n")
    (RESULTS / "net_supervisor.txt").write_text(sup.to_text())
    for pol, d in res["policies"].items():
        print(f"{pol:13s} markings={d['reachable_markings']:3d} deadlocks={d['deadlocks_with_unfinished_jobs']} "
              f"cannot_complete={d['markings_that_cannot_complete']:2d} invariants_ok={d['invariants_hold_on_all_markings']}")
    ref = res["maximally_permissive_reference"]
    print("maximally permissive reference:", ref["reachable_markings"], "markings;",
          "supervisor equals it:", ref["supervisor"]["equals_maximally_permissive"])


if __name__ == "__main__":
    main()
