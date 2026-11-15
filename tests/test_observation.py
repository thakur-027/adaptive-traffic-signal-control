"""The observation vector: its size under every switch, and what the added features hold."""
import copy

import numpy as np
import pytest

from atsc.config import Config
from atsc.control.max_pressure import MaxPressureController
from atsc.envs.spaces import (ARRIVAL_NORM, PHASE_PRESSURE_NORM, cfg_obs_size, emergency_flags,
                              obs_size, phase_pressure)
from atsc.envs.traffic_env import MultiAgentTrafficEnv
from atsc.sim.backend import APPROACHES

# where each block starts in the shipped 33-value layout (see atsc/envs/spaces.py)
EMERGENCY, PRESSURE, RATE, TREND = slice(11, 15), slice(23, 25), slice(25, 29), slice(29, 33)


def _with(cfg, **rl):
    raw = copy.deepcopy(dict(cfg))
    raw["rl"] = dict(cfg.rl, **rl)
    return Config(raw)


def _run(env, seconds, scenario="high", seed=2, action=None):
    env._episode_seconds = seconds + 100
    obs = env.reset(scenario=scenario, seed=seed)
    i = 0
    while env._elapsed < seconds:
        act = (i // 4) % 2 if action is None else action
        obs, *_ = env.step({a: act for a in env.agents})
        i += 1
    return obs


@pytest.mark.parametrize("neighbor, pressure, demand, size", [
    (True, True, True, 33), (True, False, True, 31), (True, True, False, 25),
    (True, False, False, 23), (False, True, True, 25), (False, False, False, 15)])
def test_size_follows_the_switches(cfg, neighbor, pressure, demand, size):
    assert obs_size(cfg.n_phases, neighbor, pressure, demand) == size
    c = _with(cfg, neighbor_obs=neighbor, pressure_obs=pressure, demand_obs=demand)
    assert cfg_obs_size(c) == size
    env = MultiAgentTrafficEnv(c, backend_name="mini")
    obs = env.reset(scenario="medium", seed=0)
    assert all(v.shape == (size,) and v.dtype == np.float32 for v in obs.values())
    assert env.observation_space(env.possible_agents[0]).shape == (size,)


def test_values_stay_in_range_all_the_way_through_a_rush_hour(cfg):
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    env._episode_seconds = 900
    obs = env.reset(scenario="rush", seed=5)
    i = 0
    while env.agents:
        for v in obs.values():
            assert np.isfinite(v).all() and v.min() >= -1.0 and v.max() <= 1.0
        obs, *_ = env.step({a: (i // 6) % 2 for a in env.agents})
        i += 1


def test_pressure_inputs_are_what_max_pressure_compares(cfg):
    """The per-phase pressures of the observation pick the same phase as the max-pressure
    rule, at every junction and at every decision of a run."""
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    env._episode_seconds = 600
    obs = env.reset(scenario="high", seed=2)
    rule = MaxPressureController(cfg, env.topo)
    decisive = 0
    while env.agents:
        choice = rule.act(env)
        for iid in env.possible_agents:
            it = env.topo.get(iid)
            raw = [phase_pressure(env.backend, it, ph) for ph in it.phases]
            got = obs[iid][PRESSURE]
            assert got == pytest.approx(np.tanh(np.array(raw) / PHASE_PRESSURE_NORM), abs=1e-6)
            assert choice[iid] == int(np.argmax(raw))            # first phase wins a tie, as there
            if raw[0] != raw[1]:
                decisive += 1
                assert choice[iid] == int(np.argmax(got))
        obs, *_ = env.step(choice)
    assert decisive > 100


def test_demand_inputs_follow_the_arrivals(cfg):
    """Averaged over a run, the arrival rate read on an entry approach is the scenario's
    rate there: the arterial entries read 2.2 times the side-street ones."""
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    env._episode_seconds = 1500
    obs = env.reset(scenario="medium", seed=1)
    samples = {"N": [], "W": []}
    i = 0
    while env.agents:
        if env._elapsed >= 200:
            # J0_0 is the top-left junction: its N and W approaches are entries of the network
            for a in samples:
                samples[a].append(obs["J0_0"][RATE][APPROACHES.index(a)] * ARRIVAL_NORM)
                assert samples[a][-1] == pytest.approx(env.backend.arrival_rate("J0_0", a), abs=1e-6)
        obs, *_ = env.step({a: (i // 4) % 2 for a in env.agents})
        i += 1
    params = cfg.scenario_params("medium")
    side = params["base_arrival_vps"] * params["arrival_scale"]
    assert np.mean(samples["N"]) == pytest.approx(side, rel=0.25)
    assert np.mean(samples["W"]) == pytest.approx(side * params["arterial_boost"], rel=0.25)


def test_the_trend_is_positive_while_a_surge_builds_and_negative_while_it_ebbs(cfg):
    def mean_trend(until):
        env = MultiAgentTrafficEnv(cfg, backend_name="mini")
        _run(env, until, scenario="surge", seed=3)
        b = env.backend
        return np.mean([b.arrival_trend(i, a) for i in env.possible_agents for a in APPROACHES])
    samples_up = [mean_trend(t) for t in (420, 460, 500)]
    samples_down = [mean_trend(t) for t in (800, 840, 880)]
    assert np.mean(samples_up) > 0 > np.mean(samples_down)


def test_emergency_flag_is_half_on_the_way_and_one_at_the_stop_line(cfg):
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    _run(env, 100, scenario="medium", seed=4, action=0)          # NS green: the arterial queues
    assert not emergency_flags(env.backend)
    env.inject_emergency("ew", kind="ambulance")
    first, second = [(j, a) for j, a in env.backend.emergency_routes()[0][1]]
    flags = emergency_flags(env.backend)
    assert flags == {first: 1.0, second: 0.5}                    # waiting at one, heading for the next
    obs = env._observations()
    assert obs[first[0]][EMERGENCY][APPROACHES.index(first[1])] == 1.0
    assert obs[second[0]][EMERGENCY][APPROACHES.index(second[1])] == 0.5
    others = [i for i in env.possible_agents if i not in (first[0], second[0])]
    assert all(not obs[i][EMERGENCY].any() for i in others)

    # without the look-ahead only the junction it is waiting at sees it
    near = MultiAgentTrafficEnv(_with(cfg, emergency_lookahead=False), backend_name="mini")
    _run(near, 100, scenario="medium", seed=4, action=0)
    near.inject_emergency("ew", kind="ambulance")
    obs = near._observations()
    assert obs[first[0]][EMERGENCY][APPROACHES.index(first[1])] == 1.0
    assert not obs[second[0]][EMERGENCY].any()
