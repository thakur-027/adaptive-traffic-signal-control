"""Safety tests for the signal FSM - the property reviewers care about most.

Under thousands of random phase requests, the FSM must never:
  * hold a green shorter than min_green (excluding a run-truncated final green),
  * hold a green longer than max_green,
  * switch between two different greens without a full yellow + all-red clearance
    (so conflicting movements can never be green at the same time).
"""
import numpy as np

from atsc.envs.phases import SignalFSM, SignalState
from atsc.sim.backend import _phase_set


def _run_random(seed, steps=6000, min_g=10, max_g=60, yellow=3, all_red=2):
    phases = _phase_set("ns_ew")
    fsm = SignalFSM(phases, min_g, max_g, yellow, all_red)
    rng = np.random.default_rng(seed)
    history = []
    for t in range(steps):
        if rng.random() < 0.3:
            fsm.request(int(rng.integers(0, len(phases))))
        greens = fsm.tick()
        history.append((t, fsm.state, fsm.current, tuple(greens)))
    return history


def _green_segments(history):
    segs, cur, start = [], None, None
    for t, state, phase, greens in history:
        key = phase if state == SignalState.GREEN else None
        if key != cur:
            if cur is not None:
                segs.append((cur, start, t - 1))
            cur, start = key, t
    segs.append((cur, start, len(history) - 1))
    return [(p, s, e) for (p, s, e) in segs if p is not None]


def test_min_and_max_green_respected():
    for seed in range(3):
        segs = _green_segments(_run_random(seed))
        # The final green may be truncated by the end of the run (not a real switch),
        # so exclude it from the min-green bound; max-green still applies to all.
        last_end = segs[-1][2] if segs else -1
        for (_p, s, e) in segs:
            dur = e - s + 1
            if e < last_end:
                assert dur >= 10, f"green too short: {dur}s (seed {seed})"
            assert dur <= 60, f"green too long: {dur}s (seed {seed})"


def test_yellow_all_red_clearance_between_conflicting_greens():
    for seed in range(3):
        segs = _green_segments(_run_random(seed))
        for i in range(1, len(segs)):
            if segs[i][0] != segs[i - 1][0]:
                gap = segs[i][1] - segs[i - 1][2] - 1
                assert gap >= 3 + 2, f"insufficient clearance between greens: {gap}s"


def test_no_conflicting_greens_simultaneously():
    hist = _run_random(0)
    for _t, _state, _phase, greens in hist:
        g = set(greens)
        assert not (g & {"N", "S"} and g & {"E", "W"}), "conflicting greens active together"


def test_initial_green_holds_full_min_green():
    fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
    fsm.request(1)  # ask to switch away immediately
    greens = [bool(fsm.tick()) for _ in range(11)]
    # first 10 ticks must remain green (min-green), tick 11 (index 10) turns to yellow
    assert all(greens[:10]), "initial green ended before min-green"
    assert not greens[10], "initial green did not end promptly after min-green"


def test_request_out_of_range_raises():
    fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
    try:
        fsm.request(5)
        assert False, "expected ValueError"
    except ValueError:
        pass


def _lamp_runs(fsm, steps, request=None):
    """(state, phase, seconds) for each run of identical lamp aspects over ``steps`` ticks."""
    runs = []
    for t in range(steps):
        if request is not None:
            request(fsm, t)
        fsm.tick()
        key = (fsm.state, fsm.current)
        if runs and tuple(runs[-1][:2]) == key:
            runs[-1][2] += 1
        else:
            runs.append([*key, 1])
    return [tuple(r) for r in runs]


def test_every_green_lasts_exactly_min_green_when_a_change_is_wanted_at_once():
    fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
    runs = _lamp_runs(fsm, 200, lambda f, _t: f.request(1 - f.current))
    greens = [r for r in runs[:-1] if r[0] == SignalState.GREEN]
    assert len(greens) > 10 and {r[2] for r in greens} == {10}       # the first one included
    assert {r[2] for r in runs[:-1] if r[0] == SignalState.YELLOW} == {3}
    assert {r[2] for r in runs[:-1] if r[0] == SignalState.ALL_RED} == {2}


def test_a_green_nobody_ends_is_cut_at_exactly_max_green():
    fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
    runs = _lamp_runs(fsm, 400)                                       # never a request
    greens = [r for r in runs[:-1] if r[0] == SignalState.GREEN]
    assert len(greens) >= 5 and {r[2] for r in greens} == {60}
    assert [r[1] for r in greens] == [i % 2 for i in range(len(greens))]   # and it alternates


def test_a_change_once_begun_cannot_be_cancelled():
    fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
    fsm.request(1)
    while fsm.state == SignalState.GREEN:
        fsm.tick()
    for _ in range(3 + 2):                       # ask for the old phase all through the change
        assert fsm.state != SignalState.GREEN
        fsm.request(0)
        fsm.tick()
    assert (fsm.state, fsm.current) == (SignalState.GREEN, 1)          # the change completed
    runs = _lamp_runs(fsm, 9 + 3 + 2 + 1)        # the request is acted on after min-green
    assert runs == [(SignalState.GREEN, 1, 9), (SignalState.YELLOW, 1, 3),
                    (SignalState.ALL_RED, 1, 2), (SignalState.GREEN, 0, 1)]


def test_no_phase_waits_longer_than_max_green_plus_the_clearances():
    """Whatever is requested, and whenever: a phase is never without green for longer than
    the other phase's max_green plus the two clearances around it (two-phase scheme)."""
    for seed in range(5):
        rng = np.random.default_rng(100 + seed)
        fsm = SignalFSM(_phase_set("ns_ew"), 10, 60, 3, 2)
        since = {0: 0, 1: 0}                      # seconds since each phase last had green
        for _ in range(8000):
            if rng.random() < 0.6:                # mostly: ask for whatever is green now
                fsm.request(fsm.current if rng.random() < 0.8 else int(rng.integers(0, 2)))
            fsm.tick()
            for p in since:
                since[p] = 0 if (fsm.state == SignalState.GREEN and fsm.current == p) else since[p] + 1
                assert since[p] <= 60 + 2 * (3 + 2), f"phase {p} waited {since[p]} s (seed {seed})"
