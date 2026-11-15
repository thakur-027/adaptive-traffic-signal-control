"""Per-intersection signal state machine that ENFORCES safety.

The RL agent never drives the lights directly. It only requests a target green phase.
This finite-state machine turns that request into a physically safe sequence:

    GREEN(p) --(request p', min-green satisfied)--> YELLOW --> ALL_RED --> GREEN(p')

Guarantees (verified in tests/test_phases_safety.py):
  * a green phase always holds for at least min_green_s before any switch;
  * every switch between two different greens is separated by yellow_s of amber AND
    all_red_s of all-red clearance, so conflicting movements never overlap;
  * a green is forced to end after max_green_s (anti-starvation);
  * a change, once begun, is completed: a request made during YELLOW or ALL_RED cannot
    cancel it, it is acted on from the green that follows;
  * during YELLOW and ALL_RED no approach is given green (collision-free).

The machine ticks once per simulated second. active_green() returns the approaches that
currently have green (empty during transitions), which the environment passes straight to
the simulation backend.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Tuple

from atsc.sim.backend import PhaseDef


class SignalState(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    ALL_RED = "all_red"


class SignalFSM:
    """Safety-enforcing signal controller for a single intersection."""

    def __init__(self, phases: List[PhaseDef], min_green_s: int, max_green_s: int,
                 yellow_s: int, all_red_s: int, start_phase: int = 0) -> None:
        assert len(phases) >= 1
        self.phases = phases
        self.n_phases = len(phases)
        self.min_green = int(min_green_s)
        self.max_green = int(max_green_s)
        self.yellow = int(yellow_s)
        self.all_red = int(all_red_s)

        self.current = int(start_phase)
        self.target = int(start_phase)
        self.state = SignalState.GREEN
        self.timer = 0            # seconds spent in the current state
        self.green_elapsed = 0    # seconds since the current green began
        self._next = int(start_phase)  # the phase a change in progress leads to
        self._switch_started = False   # latched True on the second a switch begins
        # The very first green gets one "settling" tick before its elapsed timer starts
        # counting. A green entered mid-run does not: the tick that ends the all-red already
        # shows its first second of green, so both kinds last exactly the same time.
        self._settle_green = True

    # -- external control --
    def request(self, target_phase: int) -> None:
        """Ask the controller to move to target_phase (acted on when eligible).

        During YELLOW and ALL_RED the request is only remembered: the change in progress
        runs to its green, and the request is acted on from there (after min-green).
        """
        if not (0 <= target_phase < self.n_phases):
            raise ValueError(f"target_phase {target_phase} out of range [0,{self.n_phases})")
        self.target = int(target_phase)

    # -- eligibility --
    def can_switch_now(self) -> bool:
        return (self.state == SignalState.GREEN
                and self.green_elapsed >= self.min_green
                and self.n_phases > 1)

    # -- time step --
    def tick(self) -> Tuple[str, ...]:
        """Advance one simulated second; return the approaches with green now."""
        self._switch_started = False
        self.timer += 1

        if self.state == SignalState.GREEN:
            if self._settle_green:
                # first tick in this green just holds; elapsed starts counting next tick
                self._settle_green = False
                return self.active_green()
            self.green_elapsed += 1
            want_switch = self.target != self.current
            forced = self.green_elapsed >= self.max_green
            if (want_switch and self.green_elapsed >= self.min_green) or forced:
                if forced and self.target == self.current:
                    self.target = (self.current + 1) % self.n_phases
                if self.target != self.current:
                    self._begin_transition()
        elif self.state == SignalState.YELLOW:
            if self.timer >= self.yellow:
                self._enter(SignalState.ALL_RED)
        elif self.state == SignalState.ALL_RED:
            if self.timer >= self.all_red:
                self._begin_green(self._next)

        return self.active_green()

    # -- transitions --
    def _begin_transition(self) -> None:
        self._switch_started = True
        self._next = self.target           # latched: later requests cannot cancel the change
        if self.yellow > 0:
            self._enter(SignalState.YELLOW)
        elif self.all_red > 0:
            self._enter(SignalState.ALL_RED)
        else:
            self._begin_green(self._next)

    def _enter(self, state: SignalState) -> None:
        self.state = state
        self.timer = 0

    def _begin_green(self, phase: int) -> None:
        self.current = int(phase)
        self.state = SignalState.GREEN
        self.timer = 0
        self.green_elapsed = 0
        self._settle_green = False

    # -- observation helpers --
    def active_green(self) -> Tuple[str, ...]:
        """Approaches with green right now (empty during yellow / all-red)."""
        if self.state == SignalState.GREEN:
            return self.phases[self.current].green_approaches
        return tuple()

    @property
    def switch_started(self) -> bool:
        return self._switch_started

    @property
    def phase_onehot(self) -> List[float]:
        vec = [0.0] * self.n_phases
        vec[self.current] = 1.0
        return vec

    @property
    def in_transition(self) -> bool:
        return self.state != SignalState.GREEN

    def time_since_change_frac(self) -> float:
        return min(1.5, self.green_elapsed / max(1, self.max_green))
