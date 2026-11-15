"""Tests for the evaluation math + backend/topology fundamentals."""
import numpy as np
import pandas as pd
import pytest

from atsc.eval.benchmark import improvement_table, summarize
from atsc.sim.backend import build_topology
from atsc.sim.mini_backend import MiniBackend


def _fake_df():
    rows = []
    # fixed slower than RL -> positive improvement
    for seed in range(2):
        rows.append(dict(scenario="high", controller="fixed_time", seed=seed,
                         avg_waiting_time=100.0, avg_queue=10.0, throughput=1000,
                         avg_speed=3.0, fuel_ml=1.0, co2_g=2.0, emergency_clearance_time=50.0))
        rows.append(dict(scenario="high", controller="rl", seed=seed,
                         avg_waiting_time=55.0, avg_queue=6.0, throughput=1100,
                         avg_speed=4.0, fuel_ml=0.8, co2_g=1.6, emergency_clearance_time=20.0))
    return pd.DataFrame(rows)


def test_improvement_table_math():
    df = _fake_df()
    impr = improvement_table(df)
    assert abs(impr.loc["high", "wait_reduction_%"] - 45.0) < 1e-6
    assert abs(impr.loc["high", "queue_reduction_%"] - 40.0) < 1e-6
    assert abs(impr.loc["high", "throughput_gain_%"] - 10.0) < 1e-6


def test_summarize_groups():
    df = _fake_df()
    s = summarize(df)
    assert ("high", "fixed_time") in s.index
    assert ("high", "rl") in s.index
    assert abs(s.loc[("high", "rl"), "avg_waiting_time"] - 55.0) < 1e-6


def test_topology_grid_and_neighbors(cfg):
    topo = build_topology(cfg)
    assert topo.n_intersections == cfg.network.grid_rows * cfg.network.grid_cols
    # neighbour relation is symmetric
    for it in topo:
        for approach, nid in it.neighbors.items():
            if nid is not None:
                back = topo.get(nid).neighbors
                assert it.id in back.values()


def test_mini_backend_conservation(cfg):
    """Vehicles that arrive either complete, are queued, or are in transit — nothing vanishes."""
    topo = build_topology(cfg)
    be = MiniBackend(cfg, topo)
    be.reset(cfg.scenario_params("medium"), seed=0)
    phases = topo.get(topo.order[0]).phases
    total_arrivals = 0
    total_completed = 0
    for t in range(600):
        for iid in topo.order:
            be.set_green(iid, phases[(t // 30) % 2].green_approaches)
        oc = be.step()
        total_arrivals += oc.arrivals
        total_completed += oc.completed
    queued = sum(be.queue(iid, a) for iid in topo.order for a in ["N", "E", "S", "W"])
    in_transit = len(be._transit)
    assert total_completed + queued + in_transit == total_arrivals


# --------------------------------------------------------------------------- #
# confidence intervals and the seed-by-seed comparison
# --------------------------------------------------------------------------- #
def test_ci95_is_the_student_t_interval_of_the_mean():
    from atsc.eval.benchmark import ci95
    # ten values with mean 5.5 and sample sd 3.0277: t(9) = 2.262
    assert abs(ci95(range(1, 11)) - 2.262 * 3.0276503540974917 / 10 ** 0.5) < 1e-9
    assert abs(ci95([1.0, 3.0]) - 12.706 * 2 ** 0.5 / 2 ** 0.5) < 1e-9      # 2 values: t(1)
    assert ci95([4.0, 4.0, 4.0]) == 0.0
    assert np.isnan(ci95([4.0])) and np.isnan(ci95([]))
    assert abs(ci95([1.0, float("nan"), 3.0]) - ci95([1.0, 3.0])) < 1e-12   # missing runs are skipped
    wide = ci95([float(i % 7) for i in range(200)])                          # beyond the table: 1.96
    sd = np.std([float(i % 7) for i in range(200)], ddof=1)
    assert abs(wide - 1.96 * sd / 200 ** 0.5) < 1e-9


def _paired_df():
    rows = []
    rl = {0: 20.0, 1: 22.0, 2: 21.0, 3: 30.0}
    mp = {0: 24.0, 1: 25.0, 2: 23.0, 3: 28.0}          # RL lower in seeds 0-2, higher in seed 3
    for seed in rl:
        rows.append(dict(scenario="low", controller="rl", seed=seed, avg_waiting_time=rl[seed]))
        rows.append(dict(scenario="low", controller="max_pressure", seed=seed, avg_waiting_time=mp[seed]))
        rows.append(dict(scenario="low", controller="fixed_time", seed=seed, avg_waiting_time=40.0))
    return pd.DataFrame(rows)


def test_paired_table_compares_seed_by_seed():
    from atsc.eval.benchmark import ci95, paired_table
    pt = paired_table(_paired_df(), "rl", "max_pressure")
    r = pt.loc["low"]
    diffs = [-4.0, -3.0, -2.0, 2.0]
    assert r["target"] == 23.25 and r["baseline"] == 25.0
    assert r["diff"] == -1.75 and abs(r["ci95"] - ci95(diffs)) < 1e-12
    assert abs(r["change_%"] - (-7.0)) < 1e-9
    assert r["lower_in"] == 3 and r["seeds"] == 4
    # the interval reaches 0 here, so this difference is within seed-to-seed noise ...
    assert abs(r["diff"]) < r["ci95"]
    # ... and against fixed-time it is not
    f = paired_table(_paired_df(), "rl", "fixed_time").loc["low"]
    assert f["lower_in"] == 4 and abs(f["diff"]) > f["ci95"]
    assert paired_table(_paired_df(), "rl", "nobody").empty


def test_summary_markdown_has_the_seed_by_seed_section(cfg, tmp_path):
    from atsc.eval.benchmark import _write_markdown_table, summarize
    df = _paired_df()
    for col in ("avg_queue", "throughput"):
        df[col] = 1.0
    _write_markdown_table(summarize(df), df, tmp_path / "s.md", cfg)
    text = (tmp_path / "s.md").read_text(encoding="utf-8")
    assert "## Waiting time: RL against each baseline, seed by seed" in text
    assert "**RL vs max_pressure**" in text and "**RL vs fixed_time**" in text
    assert "−1.8 ± 4.2" in text and "3 of 4" in text and "−7.0 %" in text


# --------------------------------------------------------------------------- #
# the surge scenario
# --------------------------------------------------------------------------- #
def test_surge_demand_rises_to_rush_level_and_falls_back(cfg):
    """Arrivals of the time-varying scenario: light at the start, at the level of the rush
    scenario around demand.peak_center_s, light again at the end; the others are flat."""
    topo = build_topology(cfg)

    def arrivals(scenario, seeds=range(6)):
        counts = np.zeros(1800)
        for seed in seeds:
            be = MiniBackend(cfg, topo)
            be.reset(cfg.scenario_params(scenario), seed=seed)
            for t in range(1800):
                counts[t] += be.step().arrivals
        return counts / len(list(seeds))

    surge, rush, medium = arrivals("surge"), arrivals("rush"), arrivals("medium")
    centre = int(cfg.demand.peak_center_s)
    peak = surge[centre - 60:centre + 60].mean()
    early, late = surge[:120].mean(), surge[-300:].mean()
    assert peak > 2.0 * early and peak > 2.0 * late
    assert peak == pytest.approx(rush.mean() * 0.6 * 1.6, rel=0.12)   # 0.6 x 1.6 = 0.96 of rush
    assert late == pytest.approx(medium.mean() * 0.6, rel=0.15)       # the 0.6 floor
    assert abs(medium[:600].mean() - medium[1200:].mean()) < 0.15 * medium.mean()   # flat
