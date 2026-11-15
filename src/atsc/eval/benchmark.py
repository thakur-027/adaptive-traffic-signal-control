"""Benchmarking harness: RL vs fixed-time vs max-pressure on identical seeds.

For every (controller, scenario, seed) it runs one episode, aggregates the KPIs into a tidy
table, writes outputs/benchmark_results.csv and a human-readable summary, and computes the
headline % improvement of the RL controller over fixed-time. Plots are produced by
atsc.eval.plots.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from atsc.config import project_root
from atsc.eval.metrics import run_controlled_episode
from atsc.logging_utils import get_logger

log = get_logger("atsc.eval")

METRIC_KEYS = [
    "avg_waiting_time", "avg_queue", "throughput", "avg_speed",
    "fuel_ml", "co2_g", "emergency_clearance_time",
]


def run_benchmark(cfg, controllers: Optional[List[str]] = None,
                  scenarios: Optional[List[str]] = None,
                  seeds: Optional[List[int]] = None,
                  checkpoint: Optional[str] = None,
                  backend_name: Optional[str] = None,
                  inject_emergency: Optional[bool] = None,
                  out_dir: Optional[str] = None) -> pd.DataFrame:
    controllers = controllers or list(cfg.eval.controllers)
    scenarios = scenarios or list(cfg.eval.scenarios)
    seeds = seeds or list(cfg.eval.seeds)
    inject_emergency = cfg.eval.inject_emergency if inject_emergency is None else inject_emergency
    # the published numbers are from the built-in simulator: use it unless told otherwise,
    # even when SUMO happens to be installed (cfg.backend 'auto' would pick SUMO)
    backend_name = backend_name or cfg.get_path("eval.backend") or None
    out = Path(out_dir) if out_dir else (project_root() / cfg.eval.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    rows: List[Dict] = []
    total = len(controllers) * len(scenarios) * len(seeds)
    done = 0
    log.info("Benchmarking %d runs on the '%s' backend: controllers=%s scenarios=%s seeds=%s",
             total, backend_name or cfg.backend, controllers, scenarios, seeds)

    for controller in controllers:
        skip_controller = False
        for scenario in scenarios:
            if skip_controller:
                break
            for seed in seeds:
                try:
                    m = run_controlled_episode(
                        cfg, controller, scenario, seed,
                        backend_name=backend_name, checkpoint=checkpoint,
                        inject_emergency=inject_emergency,
                    )
                    rows.append(m)
                except FileNotFoundError as exc:
                    log.error("Skipping '%s' controller: %s",
                              controller, str(exc).splitlines()[0])
                    skip_controller = True
                    break
                done += 1
                if done % max(1, total // 10) == 0 or done == total:
                    log.info("  progress %d/%d", done, total)

    df = pd.DataFrame(rows)
    if df.empty:
        log.warning("No benchmark rows produced.")
        return df

    csv_path = out / "benchmark_results.csv"
    df.to_csv(csv_path, index=False)
    log.info("Wrote raw results -> %s", csv_path)

    summary = summarize(df)
    summary.to_csv(out / "benchmark_summary.csv")
    _print_summary(summary, df)
    _write_markdown_table(summary, df, out / "benchmark_summary.md", cfg)
    return df


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    keys = [k for k in METRIC_KEYS if k in df.columns]
    return df.groupby(["scenario", "controller"])[keys].mean()


def improvement_table(df: pd.DataFrame, baseline: str = "fixed_time",
                      target: str = "rl") -> pd.DataFrame:
    means = df.groupby(["scenario", "controller"]).mean(numeric_only=True)
    out = {}
    for scen in df["scenario"].unique():
        try:
            base = means.loc[(scen, baseline)]
            tgt = means.loc[(scen, target)]
        except KeyError:
            continue
        out[scen] = {
            "wait_reduction_%": round(100.0 * (base["avg_waiting_time"] - tgt["avg_waiting_time"]) / base["avg_waiting_time"], 1),
            "queue_reduction_%": round(100.0 * (base["avg_queue"] - tgt["avg_queue"]) / base["avg_queue"], 1),
            "throughput_gain_%": round(100.0 * (tgt["throughput"] - base["throughput"]) / max(1e-9, base["throughput"]), 1),
        }
    return pd.DataFrame(out).T


# two-sided 95 % Student t quantiles by degrees of freedom (no SciPy dependency)
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042}


def ci95(values) -> float:
    """Half-width of the 95 % confidence interval of the mean (Student t); nan below 2 values."""
    v = [float(x) for x in values if x == x]
    n = len(v)
    if n < 2:
        return float("nan")
    mean = sum(v) / n
    sd = (sum((x - mean) ** 2 for x in v) / (n - 1)) ** 0.5
    dof = n - 1
    t = _T95.get(dof) or _T95[max(k for k in _T95 if k <= dof)] if dof <= 30 else 1.96
    return t * sd / n ** 0.5


def paired_table(df: pd.DataFrame, target: str = "rl", baseline: str = "fixed_time",
                 metric: str = "avg_waiting_time") -> pd.DataFrame:
    """``target`` against ``baseline`` on the same seeds: per scenario the mean of the
    per-seed differences (target minus baseline), its 95 % interval, the change in % of the
    baseline's mean, and in how many seeds the target was lower."""
    out = {}
    for scen, g in df.groupby("scenario", sort=False):
        wide = g.pivot(index="seed", columns="controller", values=metric)
        if target not in wide or baseline not in wide:
            continue
        wide = wide[[target, baseline]].dropna()
        if wide.empty:
            continue
        diff = wide[target] - wide[baseline]
        out[scen] = {"target": wide[target].mean(), "baseline": wide[baseline].mean(),
                     "diff": diff.mean(), "ci95": ci95(diff),
                     "change_%": 100.0 * diff.mean() / wide[baseline].mean(),
                     "lower_in": int((diff < 0).sum()), "seeds": int(len(diff))}
    return pd.DataFrame(out).T


def _print_summary(summary: pd.DataFrame, df: pd.DataFrame) -> None:
    log.info("\n===== MEAN METRICS (per scenario x controller) =====\n%s",
             summary.round(2).to_string())
    impr = improvement_table(df)
    if not impr.empty:
        log.info("\n===== RL IMPROVEMENT vs FIXED-TIME =====\n%s", impr.to_string())
        avg = impr["wait_reduction_%"].mean()
        verdict = "PASS" if avg > 0 else "REVIEW"
        log.info("HEADLINE: RL reduces average waiting time by %.1f%% vs fixed-time "
                 "(mean across scenarios) [%s]", avg, verdict)


def _md_table(header: List[str], rows: List[List[str]], align: List[str]) -> str:
    """A GitHub-flavoured markdown table (no optional dependency such as ``tabulate``)."""
    widths = [max(len(str(c)) for c in col) for col in zip(header, *rows)]
    fmt = lambda cells: "| " + " | ".join(  # noqa: E731
        str(c).rjust(w) if a == "r" else str(c).ljust(w)
        for c, w, a in zip(cells, widths, align)) + " |"
    rule = "|" + "|".join((":" + "-" * (w + 1)) if a == "l" else ("-" * (w + 1) + ":")
                          for w, a in zip(widths, align)) + "|"
    return "\n".join([fmt(header), rule] + [fmt(r) for r in rows])


def _signed(value: float) -> str:
    """'-26.5 %' style with a real minus sign, as in README.md and REPORT.md."""
    if value != value:
        return "n/a"
    text = f"{abs(value):.1f} %"
    return ("\u2212" if value < 0 else "+" if value > 0 else "") + text


def _signed_s(value: float) -> str:
    return ("\u2212" if value < 0 else "+" if value > 0 else "") + f"{abs(value):.1f}"


def _shown(path: Path) -> str:
    """A path as the documents write it: relative to the project root where possible."""
    try:
        return path.resolve().relative_to(project_root().resolve()).as_posix()
    except ValueError:
        return path.name


def _write_markdown_table(summary: pd.DataFrame, df: pd.DataFrame, path: Path, cfg) -> None:
    impr = improvement_table(df)
    seeds = sorted(int(s) for s in df["seed"].unique())
    present = list(df["scenario"].unique())
    order = [s for s in cfg.eval.scenarios if s in present] + \
            [s for s in present if s not in cfg.eval.scenarios]
    controllers = [c for c in cfg.eval.controllers if c in set(df["controller"])] + \
                  [c for c in df["controller"].unique() if c not in cfg.eval.controllers]
    means = df.groupby(["scenario", "controller"]).mean(numeric_only=True)

    def pivot(metric: str, digits: int) -> str:
        rows = []
        for scen in order:
            cells = [scen]
            for ctrl in controllers:
                try:
                    v = float(means.loc[(scen, ctrl), metric])
                    cells.append("n/a" if v != v else f"{v:.{digits}f}")
                except KeyError:
                    cells.append("")
            rows.append(cells)
        return _md_table(["scenario"] + controllers, rows, ["l"] + ["r"] * len(controllers))

    lines = ["# Benchmark Summary", ""]
    lines.append(f"Grid: {cfg.network.grid_rows}x{cfg.network.grid_cols} | "
                 f"seeds: {seeds} | episode: {cfg.eval.episode_seconds}s | "
                 f"means over the seeds of {_shown(path.parent / 'benchmark_results.csv')}\n")
    lines.append("## Average waiting time (s) by scenario and controller\n")
    lines.append(pivot("avg_waiting_time", 1))
    if len(seeds) > 1:
        lines.append("\n## Waiting time: RL against each baseline, seed by seed\n")
        lines.append("Each row compares the two controllers on the same seeds (identical traffic). "
                     "*Difference* is RL minus the baseline, averaged over the seeds, with its "
                     "95 % confidence interval (Student t): negative means RL waits less, and an "
                     "interval that does not reach 0 means the difference is beyond seed-to-seed "
                     "noise. *RL lower in* counts the seeds where RL's waiting time was lower.\n")
        for base in [c for c in controllers if c != "rl"]:
            pt = paired_table(df, "rl", base)
            if pt.empty:
                continue
            rows = []
            for scen in order:
                if scen in pt.index:
                    r = pt.loc[scen]
                    rows.append([scen, f"{r['baseline']:.1f}", f"{r['target']:.1f}",
                                 f"{_signed_s(r['diff'])} \u00b1 {r['ci95']:.1f}",
                                 _signed(r["change_%"]), f"{int(r['lower_in'])} of {int(r['seeds'])}"])
            lines.append(f"**RL vs {base}**\n")
            lines.append(_md_table(["scenario", f"{base} (s)", "rl (s)", "difference (s)",
                                    "change", "RL lower in"], rows, ["l", "r", "r", "r", "r", "r"]))
            lines.append("")
    lines.append("\n## Average queue (veh/intersection)\n")
    lines.append(pivot("avg_queue", 1))
    lines.append("\n## Throughput (vehicles completed)\n")
    lines.append(pivot("throughput", 0))
    if "emergency_clearance_time" in df.columns:
        lines.append("\n## Emergency clearance time (s)\n")
        lines.append(pivot("emergency_clearance_time", 1))
    if not impr.empty:
        lines.append("\n## RL vs fixed-time: change (%)\n")
        lines.append("Negative = RL is lower. For waiting time and queue length lower is better; "
                     "for throughput higher is better. Same sign convention as README.md.\n")
        rows = []
        for scen in order:
            if scen in impr.index:
                r = impr.loc[scen]
                rows.append([scen, _signed(-r["wait_reduction_%"]), _signed(-r["queue_reduction_%"]),
                             _signed(r["throughput_gain_%"])])
        mean = impr.mean(numeric_only=True)
        rows.append(["**mean**", _signed(-mean["wait_reduction_%"]),
                     _signed(-mean["queue_reduction_%"]), _signed(mean["throughput_gain_%"])])
        lines.append(_md_table(["scenario", "waiting time", "queue", "throughput"], rows,
                               ["l", "r", "r", "r"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Wrote markdown summary -> %s", path)
