"""Training: emergency vehicles are part of it, the time limit is not a terminal state, and
the model is selected on every scenario of the curriculum."""
import copy

import numpy as np
import pytest

from atsc.config import Config
from atsc.seeding import derive_seed
from atsc.train.trainer import Trainer


def _cfg(cfg, tmp_path, **train):
    raw = copy.deepcopy(dict(cfg))
    raw["rl"] = dict(cfg.rl, nn_backend="numpy", min_buffer=8, batch_size=8)
    raw["train"] = dict(cfg.train, quick_episodes=2, episode_seconds=600, eval_every=1,
                        eval_seeds=1, curriculum=["high", "surge"],
                        checkpoint_dir=str(tmp_path / "models"), log_dir=str(tmp_path / "logs"),
                        **train)
    return Config(raw)


def _spy(trainer):
    """Record every dispatch and every stored transition of a trainer."""
    seen = {"dispatched": [], "dones": [], "max_active": 0, "preemption": []}
    inject, observe = trainer.env.inject_emergency, trainer.learner.observe

    def spy_inject(corridor=None, kind="ambulance"):
        seen["dispatched"].append((kind, corridor))
        seen["preemption"].append(trainer.env._emergency_ctrl)
        vid = inject(corridor, kind=kind)
        seen["max_active"] = max(seen["max_active"], trainer.env.backend.active_emergencies())
        return vid

    def spy_observe(obs, actions, rewards, next_obs, dones):
        seen["dones"].append(dict(dones))
        return observe(obs, actions, rewards, next_obs, dones)

    trainer.env.inject_emergency = spy_inject
    trainer.learner.observe = spy_observe
    return seen


def test_emergency_vehicles_are_dispatched_during_training_with_no_rule_attached(cfg, tmp_path):
    trainer = Trainer(_cfg(cfg, tmp_path, emergency_gap_s=60), quick=True)
    seen = _spy(trainer)
    trainer._run_episode("high", seed=11)
    kinds = {k for k, _c in seen["dispatched"]}
    assert len(seen["dispatched"]) >= 4 and len(kinds) >= 2, seen["dispatched"]
    assert kinds <= {"ambulance", "police", "fire"}
    assert {c for _k, c in seen["dispatched"]} <= {"ew", "ns"}
    assert seen["max_active"] <= 2, "at most two emergency vehicles at once"
    assert all(ctrl is None for ctrl in seen["preemption"]), "training attaches no preemption rule"


def test_no_emergency_vehicles_when_the_gap_is_zero_and_the_traffic_is_the_same(cfg, tmp_path):
    """The dispatches come from their own random stream: with or without them, the same
    vehicles arrive at the same seconds."""
    def arrivals(gap):
        trainer = Trainer(_cfg(cfg, tmp_path, emergency_gap_s=gap), quick=True)
        seen = _spy(trainer)
        counts, step = [], trainer.env.backend.step

        def counting_step():
            out = step()
            counts.append(out.arrivals)
            return out
        trainer.env.backend.step = counting_step
        trainer._run_episode("high", seed=11)
        return counts, seen["dispatched"]

    without, none = arrivals(0)
    with_emergencies, some = arrivals(60)
    assert none == [] and some
    assert without == with_emergencies


def test_the_time_limit_is_not_stored_as_a_terminal_state(cfg, tmp_path):
    trainer = Trainer(_cfg(cfg, tmp_path), quick=True)
    seen = _spy(trainer)
    _reward, steps, _loss = trainer._run_episode("surge", seed=3)
    assert steps == 600 // cfg.signal.decision_interval_s == len(seen["dones"])
    assert not any(any(d.values()) for d in seen["dones"]), "the last step must bootstrap too"


def test_model_selection_uses_every_curriculum_scenario_on_fixed_seeds(cfg, tmp_path):
    c = _cfg(cfg, tmp_path)
    trainer = Trainer(c, quick=True)
    calls = []
    trainer._greedy_eval = lambda scenario, seed: calls.append((scenario, seed)) or float(len(calls))
    first = trainer._greedy_eval_all(seed=1)
    again = list(calls)
    calls.clear()
    trainer._greedy_eval_all(seed=999)                     # a later evaluation
    assert again == calls == [("high", derive_seed(c.seed, "select", "high", 0)),
                              ("surge", derive_seed(c.seed, "select", "surge", 0))]
    assert first == pytest.approx(np.mean([1.0, 2.0]))
    benchmark_seeds = set(cfg.eval.seeds)
    assert not benchmark_seeds & {seed for _s, seed in calls}, "selection must not see benchmark seeds"


def test_a_quick_run_writes_a_checkpoint_that_records_its_settings(cfg, tmp_path):
    from atsc.control.rl_controller import RLController
    from atsc.sim.backend import build_topology
    c = _cfg(cfg, tmp_path)
    path = Trainer(c, quick=True).train()
    meta = RLController(c, build_topology(c), checkpoint=str(path)).metadata
    assert meta["obs_dim"] == 33 and meta["seed"] == c.seed
    assert meta["pressure_obs"] and meta["demand_obs"] and meta["emergency_lookahead"]
    assert meta["curriculum"] == ["high", "surge"]
    log = (tmp_path / "logs" / "train_quick.csv").read_text().splitlines()
    assert len(log) == 1 + 2 and log[1].split(",")[1] == "high" and log[2].split(",")[1] == "surge"
