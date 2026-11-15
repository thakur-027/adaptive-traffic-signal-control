"""Observation / action space construction and the per-agent state vector.

The state fed to each intersection's agent is assembled here so the exact layout is in
one documented place (and testable). For agent *i* the observation is the concatenation
of:

    [ per-approach queue (normalised) ]            # 4 values (N,E,S,W)
    [ per-approach waiting time (normalised) ]     # 4 values
    [ current-phase one-hot ]                      # n_phases values
    [ green-time-so-far / max_green ]              # 1 value
    [ per-approach emergency flag ]                # 4 values
    [ neighbour pressure (normalised), 4 sides ]   # 4 values (0 where no neighbour)
    [ neighbour active-phase index / n_phases ]    # 4 values
    [ per-phase pressure (normalised) ]            # n_phases values   (rl.pressure_obs)
    [ per-approach arrival rate (normalised) ]     # 4 values          (rl.demand_obs)
    [ per-approach arrival trend (normalised) ]    # 4 values          (rl.demand_obs)

With the default 2-phase scheme this is 4+4+2+1+4+4+4+2+4+4 = 33 features per agent.
``rl.neighbor_obs: false`` drops the 8 neighbour features, ``rl.pressure_obs: false`` the
per-phase pressures and ``rl.demand_obs: false`` the 8 demand features.

*Per-phase pressure* is exactly what the max-pressure rule compares: for the approaches a
phase serves, the queue minus the queue its straight-through traffic joins downstream.
*Arrival rate* is the number of vehicles joining an approach per second over about the last
30 s; *arrival trend* is that rate minus the 120 s one, positive while demand is rising.

The *emergency flag* of an approach is 1 while an emergency vehicle waits on it. With
``rl.emergency_lookahead: true`` it is 0.5 while one is still on its way to that approach
(any junction ahead on its route), which is what lets the agents open a path before it
arrives; with ``false`` an approach only shows the vehicles already waiting on it.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np

from atsc.sim.backend import APPROACHES, APPROACH_TO_TRAVEL, TRAVEL_TO_APPROACH, NetworkTopo

# normalisation constants (state features are scaled to roughly [0,1])
QUEUE_NORM = 20.0        # ~ a long queue on one approach
WAIT_NORM = 100.0        # ~ a long cumulative wait (s)
PRESSURE_NORM = 40.0
PHASE_PRESSURE_NORM = 20.0
ARRIVAL_NORM = 0.5       # veh/s: one lane's saturation flow
TREND_NORM = 0.2         # veh/s


def obs_options(cfg) -> Dict[str, bool]:
    """The observation switches of ``config.yaml`` (``rl.*``), with their defaults."""
    return {"neighbor_obs": bool(cfg.rl.neighbor_obs),
            "pressure_obs": bool(cfg.get_path("rl.pressure_obs", False)),
            "demand_obs": bool(cfg.get_path("rl.demand_obs", False)),
            "emergency_lookahead": bool(cfg.get_path("rl.emergency_lookahead", False))}


def cfg_obs_size(cfg) -> int:
    o = obs_options(cfg)
    return obs_size(cfg.n_phases, o["neighbor_obs"], o["pressure_obs"], o["demand_obs"])


def obs_size(n_phases: int, neighbor_obs: bool, pressure_obs: bool = False,
             demand_obs: bool = False) -> int:
    base = len(APPROACHES) * 2 + n_phases + 1 + len(APPROACHES)  # queue,wait,phase,green,emg
    if neighbor_obs:
        base += len(APPROACHES) * 2  # neighbour pressure + neighbour phase per side
    if pressure_obs:
        base += n_phases
    if demand_obs:
        base += len(APPROACHES) * 2  # arrival rate + trend per approach
    return base


def emergency_flags(backend) -> Dict[tuple, float]:
    """``{(junction, approach): flag}`` for every approach an emergency vehicle is waiting on
    (1.0) or still has ahead of it on its route (0.5)."""
    flags: Dict[tuple, float] = {}
    for _vid, legs, eta in backend.emergency_routes():
        for k, key in enumerate(legs):
            value = 1.0 if (k == 0 and eta <= 0.0) else 0.5
            if value > flags.get(tuple(key), 0.0):
                flags[tuple(key)] = value
    return flags


def phase_pressure(backend, it, phase) -> float:
    """Queue on the approaches ``phase`` serves minus the queues they feed downstream."""
    pressure = 0.0
    for approach in phase.green_approaches:
        travel = APPROACH_TO_TRAVEL[approach]
        neigh = it.neighbors.get(travel)
        down = backend.queue(neigh, TRAVEL_TO_APPROACH[travel]) if neigh is not None else 0
        pressure += backend.queue(it.id, approach) - down
    return pressure


def build_observation(
    backend,
    topo: NetworkTopo,
    tls_id: str,
    fsm,
    fsms: Dict[str, "object"],
    neighbor_obs: bool,
    pressure_obs: bool = False,
    demand_obs: bool = False,
    emergency: Dict[tuple, float] = None,
) -> np.ndarray:
    """Assemble the normalised observation vector for one intersection.

    ``emergency`` is :func:`emergency_flags` computed once for the whole grid (look-ahead
    on); ``None`` means: only the vehicles waiting at this junction.
    """
    it = topo.get(tls_id)
    feats: List[float] = []

    # 1) queues per approach
    for a in APPROACHES:
        feats.append(min(1.0, backend.queue(tls_id, a) / QUEUE_NORM))
    # 2) waiting time per approach
    for a in APPROACHES:
        feats.append(min(1.0, backend.waiting_time(tls_id, a) / WAIT_NORM))
    # 3) current phase one-hot
    feats.extend(fsm.phase_onehot)
    # 4) normalised green time so far
    feats.append(fsm.time_since_change_frac())
    # 5) emergency flags per approach
    for a in APPROACHES:
        if emergency is None:
            feats.append(1.0 if backend.emergency_present(tls_id, a) else 0.0)
        else:
            feats.append(emergency.get((tls_id, a), 0.0))

    # 6) neighbour coordination features
    if neighbor_obs:
        for a in APPROACHES:
            neigh = it.neighbors.get(a)
            if neigh is None:
                feats.append(0.0)  # pressure
            else:
                p = backend.intersection_pressure(neigh)
                feats.append(float(np.tanh(p / PRESSURE_NORM)))
        for a in APPROACHES:
            neigh = it.neighbors.get(a)
            if neigh is None or neigh not in fsms:
                feats.append(0.0)
            else:
                nf = fsms[neigh]
                feats.append(nf.current / max(1, nf.n_phases))

    # 7) what the max-pressure rule looks at
    if pressure_obs:
        for phase in it.phases:
            feats.append(float(np.tanh(phase_pressure(backend, it, phase) / PHASE_PRESSURE_NORM)))

    # 8) demand: arrival rate and its trend per approach
    if demand_obs:
        for a in APPROACHES:
            feats.append(min(1.0, backend.arrival_rate(tls_id, a) / ARRIVAL_NORM))
        for a in APPROACHES:
            feats.append(float(np.clip(backend.arrival_trend(tls_id, a) / TREND_NORM, -1.0, 1.0)))

    return np.asarray(feats, dtype=np.float32)
