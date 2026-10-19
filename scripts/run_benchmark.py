"""Resource measurements (execution time, memory) for the C++ engine and the Python reference.

*** These numbers depend on the machine. Re-run on the device you want to quote. ***
"""
import platform
import subprocess
import sys
import time
import tracemalloc

from _common import ROOT, save_json
from petri.cell import ProcTimes, build_cell
from petri.engine_io import ENGINE, EngineSession, engine_available
from petri.timed import simulate


def cpu_model() -> str:
    """x86 exposes 'model name'; Raspberry Pi / other ARM boards expose 'Model' or 'Hardware'."""
    try:
        lines = open("/proc/cpuinfo").read().splitlines()
        for key in ("model name", "Model", "Hardware"):
            for line in lines:
                if line.startswith(key) and ":" in line:
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine() or "unknown"


def compiler() -> str:
    try:
        return subprocess.run(["g++", "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    except Exception:
        return "unknown"


def main() -> int:
    if not engine_available():
        print("C++ engine not built: run `make` first", file=sys.stderr)
        return 1
    env = dict(platform=platform.platform(), machine=platform.machine(), cpu=cpu_model(), python=platform.python_version(),
               compiler=compiler(), build_flags="-O2 -std=c++17", engine=str(ENGINE.relative_to(ROOT)))
    out = dict(environment=env, cases=[])
    cases = [("demo batch 2A+2B", (2, 2), 100_000, 2_000), ("long run 100A+100B", (100, 100), 2_000, 20)]
    for label, batch, reps_cpp, reps_py in cases:
        net = build_cell("supervisor", batch=batch, times=ProcTimes(4, 4, 4, 4), preload=False)
        arrivals = [(0, "A_queue", batch[0]), (0, "B_queue", batch[1])]
        sess = EngineSession(net)
        cpp = sess.bench(arrivals, batch, reps_cpp)
        sess.close()
        # Python reference
        for _ in range(3):
            simulate(net, arrivals, batch, record=False)
        t0 = time.perf_counter()
        for _ in range(reps_py):
            res = simulate(net, arrivals, batch, record=False)
        py_run_ns = (time.perf_counter() - t0) / reps_py * 1e9
        tracemalloc.start()
        res = simulate(net, arrivals, batch, record=False)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        firings = cpp["transition_firings_per_run"]
        out["cases"].append(dict(
            label=label, batch=list(batch), makespan_ticks=res.end_time, firings_per_run=firings,
            cpp=cpp,
            python=dict(reps=reps_py, mean_run_ns=py_run_ns, mean_ns_per_firing=py_run_ns / firings,
                        tracemalloc_peak_kb=peak / 1024),
            speedup=py_run_ns / cpp["mean_run_ns"]))
        print(f"{label}: C++ {cpp['mean_run_ns']/1e3:.2f} us/run ({cpp['mean_ns_per_firing']:.0f} ns/firing, "
              f"p99 step {cpp['step_ns_p99']} ns, peak RSS {cpp['peak_rss_kb']} kB) | "
              f"Python {py_run_ns/1e3:.1f} us/run | speed-up x{py_run_ns / cpp['mean_run_ns']:.0f}")
    save_json("benchmark.json", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
