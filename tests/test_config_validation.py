"""config.yaml validation of the keys behind the observation, the reward, the demand curve,
the emergency modes and the benchmark lists: a wrong value gives one readable error."""
import copy

import pytest

from atsc.config import Config, validate_config


def _changed(cfg, dotted, value):
    raw = copy.deepcopy(dict(cfg))
    node = raw
    *parents, leaf = dotted.split(".")
    for key in parents:
        node = node[key]
    node[leaf] = value
    return Config(raw)


def test_the_shipped_config_is_valid(cfg):
    validate_config(cfg)


@pytest.mark.parametrize("dotted, value, fragment", [
    ("rl.pressure_obs", "yes", "rl.pressure_obs must be true or false"),
    ("rl.demand_obs", 1, "rl.demand_obs must be true or false"),
    ("rl.emergency_lookahead", "on", "rl.emergency_lookahead must be true or false"),
    ("reward.w_emergency_wait", -1, "reward.w_emergency_wait must be a number >= 0"),
    ("reward.w_emergency_wait", "6", "reward.w_emergency_wait must be a number >= 0"),
    ("train.emergency_gap_s", -5, "train.emergency_gap_s must be a number >= 0"),
    ("train.eval_seeds", 0, "train.eval_seeds must be a whole number >= 1"),
    ("demand.peak_width_s", 0, "demand.peak_width_s must be a number > 0"),
    ("demand.peak_center_s", -1, "demand.peak_center_s must be a number >= 0"),
    ("train.curriculum", ["low", "tsunami"], "train.curriculum names unknown scenarios: tsunami"),
    ("eval.scenarios", [], "eval.scenarios must be a non-empty list"),
    ("eval.seeds", [0, 1, 1], "eval.seeds must not repeat a seed"),
    ("eval.seeds", [0, "a"], "eval.seeds must be a non-empty list of whole numbers"),
    ("emergency.unassisted", ["nobody"], "emergency.unassisted must be a list of controllers"),
    ("emergency.unassisted", ["rl"], "cannot be in both emergency.corridor and emergency.unassisted"),
])
def test_a_wrong_value_is_named(cfg, dotted, value, fragment):
    with pytest.raises(ValueError) as err:
        validate_config(_changed(cfg, dotted, value))
    assert fragment in str(err.value)


@pytest.mark.parametrize("dotted, value", [
    ("train.emergency_gap_s", 0),                 # 0 switches training emergencies off
    ("reward.w_emergency_wait", 0.0),
    ("emergency.unassisted", ["max_pressure"]),
    ("rl.pressure_obs", False),
])
def test_allowed_values_pass(cfg, dotted, value):
    validate_config(_changed(cfg, dotted, value))


def test_the_new_keys_are_optional(cfg):
    """A config written before these keys existed still loads, with the old behaviour."""
    from atsc.envs.spaces import cfg_obs_size, obs_options
    raw = copy.deepcopy(dict(cfg))
    for key in ("pressure_obs", "demand_obs", "emergency_lookahead"):
        del raw["rl"][key]
    del raw["reward"]["w_emergency_wait"], raw["train"]["emergency_gap_s"], raw["train"]["eval_seeds"]
    old = Config(raw)
    validate_config(old)
    assert cfg_obs_size(old) == 23
    assert obs_options(old) == {"neighbor_obs": True, "pressure_obs": False,
                                "demand_obs": False, "emergency_lookahead": False}
