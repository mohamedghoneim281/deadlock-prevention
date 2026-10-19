import pytest

from petri.cell import ProcTimes, build_cell
from petri.crosscheck import py_replay, run_crosscheck
from petri.engine_io import EngineSession, engine_available

pytestmark = pytest.mark.skipif(not engine_available(), reason="C++ engine not built (run `make`)")


def test_python_and_cpp_agree_on_a_campaign():
    rep = run_crosscheck(n_sim=40, n_walks=25, seed=99)
    assert rep.ok, rep.details
    assert rep.simulate_runs == 120 and rep.replay_steps > 1000


def test_cross_check_is_not_vacuous():
    """If the C++ side is given a different net, the harness must report a mismatch."""
    times = ProcTimes(4, 4, 4, 4)
    arrivals = [(0, "A_queue", 2), (0, "B_queue", 2)]
    py_net = build_cell("supervisor", times=times, preload=False)
    wrong = EngineSession(build_cell("unrestricted", times=times, preload=False))
    try:
        assert wrong.simulate(arrivals) != simulate_py(py_net, arrivals)
    finally:
        wrong.close()


def simulate_py(net, arrivals):
    from petri.timed import simulate
    return simulate(net, arrivals).log


def test_cpp_rejects_the_interlocked_command_like_python():
    net = build_cell("supervisor")
    sess = EngineSession(net)
    try:
        tr = ["FIRE A_load", "FIRE B_load"]      # permission token already taken by A_load
        rc_cpp, out_cpp = sess.replay(tr)
        rc_py, out_py = py_replay(net, tr)
        assert rc_cpp == rc_py == 2 and out_cpp == out_py
        assert out_cpp[-1] == "ERROR|2|B_load|not enabled"
    finally:
        sess.close()
