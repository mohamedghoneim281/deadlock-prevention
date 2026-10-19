"""Thin Python wrapper around the compiled C++ engine (build/petri_engine)."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Sequence, Tuple

from .net import PetriNet
from .timed import Arrival

ROOT = Path(__file__).resolve().parent.parent
ENGINE = Path(os.environ.get("PETRI_ENGINE", ROOT / "build" / "petri_engine"))


def engine_available() -> bool:
    return ENGINE.exists()


def scenario_text(arrivals: Sequence[Arrival], batch: Tuple[int, int]) -> str:
    lines = [f"arrive {t} {p} {n}" for t, p, n in arrivals]
    lines += [f"goal A_out {batch[0]}", f"goal B_out {batch[1]}"]
    return "\n".join(lines) + "\n"


def _run(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run([str(ENGINE)] + args, capture_output=True, text=True, check=False)


class EngineSession:
    """Writes the net once into a temp dir; reuse it for many scenarios/traces."""

    def __init__(self, net: PetriNet, workdir: Path | None = None) -> None:
        self._tmp = None
        if workdir is None:
            self._tmp = tempfile.TemporaryDirectory()
            workdir = Path(self._tmp.name)
        self.dir = Path(workdir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.net_path = self.dir / "net.txt"
        self.net_path.write_text(net.to_text())

    def simulate(self, arrivals: Sequence[Arrival], batch: Tuple[int, int] = (2, 2)) -> List[str]:
        sp = self.dir / "scenario.txt"
        sp.write_text(scenario_text(arrivals, batch))
        r = _run(["simulate", str(self.net_path), str(sp)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return r.stdout.splitlines()

    def replay(self, trace_lines: Sequence[str]) -> Tuple[int, List[str]]:
        tp = self.dir / "trace.txt"
        tp.write_text("\n".join(trace_lines) + "\n")
        r = _run(["replay", str(self.net_path), str(tp)])
        return r.returncode, r.stdout.splitlines()

    def bench(self, arrivals: Sequence[Arrival], batch: Tuple[int, int], reps: int) -> dict:
        sp = self.dir / "scenario.txt"
        sp.write_text(scenario_text(arrivals, batch))
        r = _run(["bench", str(self.net_path), str(sp), str(reps)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr)
        return json.loads(r.stdout)

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
