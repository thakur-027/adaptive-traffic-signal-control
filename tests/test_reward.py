"""Reward-shaping tests: sign, penalties, and the emergency bonus."""
import numpy as np

from atsc.envs.traffic_env import MultiAgentTrafficEnv


def test_reward_is_nonpositive_without_emergency(cfg):
    """With no emergencies, reward = -(delay+pressure+switch terms) <= 0."""
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    env._episode_seconds = 300
    obs = env.reset(scenario="high", seed=0)
    saw_negative = False
    while env.agents:
        _, rewards, _, _, _ = env.step({a: 0 for a in env.agents})
        for r in rewards.values():
            assert r <= 1e-6, "reward should be <= 0 without emergency clearance"
            if r < 0:
                saw_negative = True
    assert saw_negative, "expected some negative (congestion) reward at high density"
    env.close()


def test_every_phase_change_costs_the_switch_penalty(cfg):
    """The same run with and without the penalty differs by w_switch per change begun."""
    import copy
    from atsc.config import Config

    def run(w_switch):
        raw = copy.deepcopy(dict(cfg))
        raw["reward"] = dict(cfg.reward, w_switch=w_switch)
        env = MultiAgentTrafficEnv(Config(raw), backend_name="mini")
        env._episode_seconds = 400
        env.reset(scenario="low", seed=3)
        total, changes, i = 0.0, 0, 0
        while env.agents:
            before = {a: (f.state, f.current) for a, f in env.fsms.items()}
            _, rewards, _, _, _ = env.step({a: (i // 4) % 2 for a in env.agents})
            total += sum(rewards.values())
            changes += sum(1 for a, f in env.fsms.items()
                           if f.current != before[a][1] or (f.in_transition and before[a][0].value == "green"))
            i += 1
        env.close()
        return total, changes

    free, n = run(0.0)
    paid, n2 = run(float(cfg.reward.w_switch))
    assert n == n2 and n >= 8
    assert paid < free
    assert abs((free - paid) / float(cfg.reward.w_switch) - round((free - paid) / float(cfg.reward.w_switch))) < 1e-6


def test_emergency_bonus_positive_component(cfg):
    """Clearing an emergency injects a positive reward component for some agent."""
    from atsc.control import EmergencyController
    env = MultiAgentTrafficEnv(cfg, backend_name="mini")
    env.set_emergency_controller(EmergencyController(cfg, env.topo))
    env._episode_seconds = 400
    env.reset(scenario="low", seed=2)
    env.inject_emergency("ew")
    best = -1e9
    while env.agents:
        _, rewards, _, _, _ = env.step({a: 0 for a in env.agents})
        best = max(best, max(rewards.values()))
    # at least one step should show a positive spike from the clearance bonus
    assert best > 0, "expected a positive reward spike when the emergency clears"
    env.close()


def test_a_waiting_emergency_vehicle_costs_reward_every_decision(cfg):
    """While an emergency vehicle is held at a junction, that junction's reward is lower by
    w_emergency_wait per decision than in the same run without the term."""
    import copy
    from atsc.config import Config

    def run(w):
        raw = copy.deepcopy(dict(cfg))
        raw["reward"] = dict(cfg.reward, w_emergency_wait=w, w_emergency=0.0)
        env = MultiAgentTrafficEnv(Config(raw), backend_name="mini")
        env._episode_seconds = 200
        env.reset(scenario="high", seed=1)
        env.inject_emergency("ns", kind="police")          # enters at J0_1 from the north
        out = []
        for _ in range(4):                                  # east-west stays green: it waits
            _, rewards, _, _, _ = env.step({a: 1 for a in env.agents})
            out.append(rewards["J0_1"])
        env.close()
        return out

    without, with_term = run(0.0), run(1.0)
    diffs = [a - b for a, b in zip(without, with_term)]
    assert all(0.0 <= d <= 1.0 + 1e-9 for d in diffs) and max(diffs) > 0.99
