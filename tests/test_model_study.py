"""tools/model_study.py: the five training seeds and the three ablation models are shipped,
each loads with the settings it was trained with, and the two tables are built from runs."""
import importlib.util
import pickle
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def study():
    spec = importlib.util.spec_from_file_location("model_study", ROOT / "tools" / "model_study.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_study_model_is_shipped_and_matches_its_settings(study, cfg):
    from atsc.envs.spaces import cfg_obs_size
    catalogue = study.models()
    assert list(catalogue) == ["seed42", "seed43", "seed44", "seed45", "seed46",
                               "no_pressure_obs", "no_demand_obs", "no_train_emergencies"]
    sizes = {}
    for name, (ckpt, overrides) in catalogue.items():
        assert ckpt.exists(), ckpt
        payload = pickle.loads(ckpt.read_bytes())
        meta = payload["metadata"]
        c = study.make_cfg(None, overrides)
        assert payload["obs_dim"] == cfg_obs_size(c), name
        assert meta["seed"] == c.seed and meta["pressure_obs"] is bool(c.rl.pressure_obs)
        assert meta["demand_obs"] is bool(c.rl.demand_obs)
        sizes[name] = payload["obs_dim"]
    assert sizes["no_pressure_obs"] == 31 and sizes["no_demand_obs"] == 25
    assert sizes["seed42"] == sizes["no_train_emergencies"] == 33


def test_the_shipped_model_is_the_one_selected_on_the_validation_seeds(study, cfg):
    """models/pretrained/atsc_2x2.pt is the seed model named SHIPPED, config.yaml carries
    its seed, and the published study table shows it is the lowest on the validation seeds,
    which are not benchmark seeds."""
    shipped = (ROOT / "models" / "pretrained" / "atsc_2x2.pt").read_bytes()
    assert shipped == study.models()[study.SHIPPED][0].read_bytes()
    assert study.SHIPPED == f"seed{cfg.seed}"
    assert not set(study.VALIDATION_SEEDS) & set(cfg.eval.seeds)
    summary = pd.read_csv(ROOT / "outputs" / "study" / "model_summary.csv")
    val = summary[(summary["split"] == "validation") & summary["model"].str.startswith("seed")]
    assert len(val) == 5
    assert val.loc[val["mean"].idxmin(), "model"] == study.SHIPPED


def test_the_published_study_agrees_with_the_published_benchmark(study):
    """The shipped model's row of the study is the benchmark's RL column, run for run."""
    runs = pd.read_csv(ROOT / "outputs" / "study" / "model_runs.csv")
    bench = pd.read_csv(ROOT / "outputs" / "benchmark_results.csv")
    mine = runs[(runs["split"] == "benchmark") & (runs["model"] == study.SHIPPED)]
    merged = mine.merge(bench[bench["controller"] == "rl"], on=["scenario", "seed"],
                        suffixes=("_study", "_bench"))
    assert len(merged) == len(mine) == 50
    assert (merged["avg_waiting_time_study"] - merged["avg_waiting_time_bench"]).abs().max() < 1e-3
    for base in ("fixed_time", "max_pressure"):
        a = runs[(runs["split"] == "benchmark") & (runs["model"] == base)]
        m = a.merge(bench[bench["controller"] == base], on=["scenario", "seed"], suffixes=("_s", "_b"))
        assert len(m) == 50 and (m["avg_waiting_time_s"] - m["avg_waiting_time_b"]).abs().max() < 1e-3


def test_a_small_study_runs_and_writes_the_three_tables(study, tmp_path, monkeypatch):
    names = ["seed45", "seed43", "seed42", "no_pressure_obs"]
    monkeypatch.setattr(study, "make_cfg", _small(study.make_cfg))
    monkeypatch.setattr(study, "VALIDATION_SEEDS", (100,))
    df, scenarios, seeds = study.benchmark(None, names, workers=1)
    assert scenarios == ["low", "surge"] and seeds == [0, 1]
    # benchmark seeds: every model and both baselines; validation seed: the seed models and baselines
    assert len(df) == (4 + 2) * 2 * 2 + (3 + 2) * 2 * 1
    assert set(df["model"]) == set(names) | {"fixed_time", "max_pressure"}
    assert set(df[df["split"] == "validation"]["model"]) == {"seed45", "seed43", "seed42",
                                                             "fixed_time", "max_pressure"}
    study.write_outputs(df, scenarios, seeds, names, tmp_path)
    runs = pd.read_csv(tmp_path / "model_runs.csv")
    summary = pd.read_csv(tmp_path / "model_summary.csv")
    assert len(runs) == len(df)
    bench = summary[summary["split"] == "benchmark"].set_index("model")
    assert list(bench.index) == ["fixed_time", "max_pressure"] + names
    for name in bench.index:
        part = runs[(runs["model"] == name) & (runs["split"] == "benchmark")]
        mean = part.groupby("scenario")["avg_waiting_time"].mean()
        assert bench.loc[name, "low"] == pytest.approx(mean["low"], abs=1e-3)
        assert bench.loc[name, "mean"] == pytest.approx(mean.mean(), abs=1e-3)
    text = (tmp_path / "model_study.md").read_text(encoding="utf-8")
    for heading in ("## Model selection", "## Training-to-training variation", "## Ablation"):
        assert heading in text
    assert "RL, training seed 45 (shipped)" in text and "RL, standard deviation" in text
    assert "without the per-phase pressure inputs" in text and "models below max-pressure" in text
    assert "full model, training seed 42" in text


def _small(make_cfg):
    def make(config_path, overrides):
        cfg = make_cfg(config_path, overrides)
        cfg.eval = dict(cfg.eval, scenarios=["low", "surge"], seeds=[0, 1], episode_seconds=300)
        return cfg
    return make


def test_an_unknown_or_missing_model_is_refused(study, monkeypatch, tmp_path):
    monkeypatch.setattr(study, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="is missing - train it with"):
        study.benchmark(None, ["seed42"], workers=1)
