#!/usr/bin/env python3
"""Model study: which model is shipped, how much the result depends on the training run,
and what each addition buys.

    python tools/model_study.py                 # benchmark every shipped study model
    python tools/model_study.py --train no_pressure_obs    # retrain one model (about 8 min)
    python tools/model_study.py --list

Everything runs on the built-in simulator with the benchmark's scenarios and episode length
(``eval`` in config.yaml).

*Model selection.* The recipe of config.yaml was run five times, with the training seeds 42
to 46 (``models/seeds/atsc_2x2_seedNN.pt``). The five models are compared on the validation
seeds 100 to 104, which are neither training traffic nor benchmark seeds, and the one with
the lowest mean waiting time there is the shipped model: seed 45, so config.yaml says
``seed: 45`` and ``models/pretrained/atsc_2x2.pt`` is the same file as
``models/seeds/atsc_2x2_seed45.pt``. The benchmark seeds play no part in the choice.

*Training-to-training variation.* The same five models on the benchmark's own seeds: how far
a retrain can land from the shipped model.

*Ablation.* Three more models were trained with one ingredient removed each
(``models/ablation/atsc_2x2_<name>.pt``): without the per-phase pressure inputs, without
the demand inputs, and without emergency vehicles during training. They were trained with
seed 42 and are compared with the full model of that same seed. One training run each, so a
difference smaller than the seed-to-seed spread is not evidence.

Outputs (``outputs/study/``): ``model_runs.csv`` (one row per model, scenario and seed, for
the validation and the benchmark seeds), ``model_summary.csv`` (means) and
``model_study.md`` (the three tables).
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

SEEDS = (42, 43, 44, 45, 46)
SHIPPED = "seed45"                      # lowest mean waiting time on VALIDATION_SEEDS
VALIDATION_SEEDS = (100, 101, 102, 103, 104)
ABLATION_BASE = "seed42"                # the ablation models were trained with this seed
#: name -> (config overrides, what was removed)
ABLATIONS: Dict[str, Tuple[Dict[str, object], str]] = {
    "no_pressure_obs": ({"seed": 42, "rl.pressure_obs": False},
                        "without the per-phase pressure inputs"),
    "no_demand_obs": ({"seed": 42, "rl.demand_obs": False},
                      "without the demand inputs (rate and trend)"),
    "no_train_emergencies": ({"seed": 42, "train.emergency_gap_s": 0},
                             "without emergency vehicles during training"),
}
BASELINES = ("fixed_time", "max_pressure")


def models() -> Dict[str, Tuple[Path, Dict[str, object]]]:
    """Every study model: name -> (checkpoint, config overrides it was trained with)."""
    out: Dict[str, Tuple[Path, Dict[str, object]]] = {}
    for s in SEEDS:
        out[f"seed{s}"] = (ROOT / "models" / "seeds" / f"atsc_2x2_seed{s}.pt", {"seed": s})
    for name, (overrides, _what) in ABLATIONS.items():
        out[name] = (ROOT / "models" / "ablation" / f"atsc_2x2_{name}.pt", dict(overrides))
    return out


def make_cfg(config_path, overrides: Dict[str, object]):
    from atsc.config import load_config, validate_config
    cfg = load_config(config_path)
    for dotted, value in overrides.items():
        node = cfg
        keys = dotted.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    validate_config(cfg)
    return cfg


# --------------------------------------------------------------------------- #
# training one study model
# --------------------------------------------------------------------------- #
def train(name: str, config_path) -> Path:
    import tempfile
    from atsc.train.trainer import Trainer
    ckpt, overrides = models()[name]
    cfg = make_cfg(config_path, overrides)
    trainer = Trainer(cfg)
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    trainer.ckpt_path = ckpt
    t0 = time.time()
    # only the selected checkpoint is kept: the training log and the last weights of a study
    # model go to a scratch folder (outputs/logs/train.csv stays the shipped model's log)
    with tempfile.TemporaryDirectory() as scratch:
        trainer.log_dir = Path(scratch)
        trainer.train()
    ckpt.with_name(ckpt.stem + "_final.pt").unlink(missing_ok=True)
    print(f"{name}: trained in {time.time() - t0:.0f} s -> {ckpt.relative_to(ROOT)}")
    return ckpt


# --------------------------------------------------------------------------- #
# benchmarking
# --------------------------------------------------------------------------- #
def _episode(job) -> Dict[str, object]:
    config_path, split, model, controller, ckpt, overrides, scenario, seed = job
    import logging
    logging.disable(logging.WARNING)
    from atsc.eval.metrics import run_controlled_episode
    cfg = make_cfg(config_path, overrides)
    m = run_controlled_episode(cfg, controller, scenario, seed, backend_name="mini",
                               checkpoint=ckpt, inject_emergency=bool(cfg.eval.inject_emergency))
    return {"split": split, "model": model, "scenario": scenario, "seed": seed,
            "avg_waiting_time": m["avg_waiting_time"], "avg_queue": m["avg_queue"],
            "throughput": m["throughput"]}


def benchmark(config_path, names: List[str], workers: int):
    """Run every model (and the two baselines) on the benchmark seeds, and the seed models
    on the validation seeds as well. Returns (runs, scenarios, benchmark seeds)."""
    import pandas as pd
    cfg = make_cfg(config_path, {})
    scenarios, seeds = list(cfg.eval.scenarios), list(cfg.eval.seeds)
    catalogue = models()
    splits = {"benchmark": seeds, "validation": list(VALIDATION_SEEDS)}
    jobs = []
    for split, split_seeds in splits.items():
        for base in BASELINES:
            jobs += [(config_path, split, base, base, None, {}, sc, sd)
                     for sc in scenarios for sd in split_seeds]
    for name in names:
        ckpt, overrides = catalogue[name]
        if not ckpt.exists():
            raise SystemExit(f"{ckpt.relative_to(ROOT)} is missing - train it with "
                             f"`python tools/model_study.py --train {name}`")
        # only the observation switches matter when a model is played back
        play = {k: v for k, v in overrides.items() if k.startswith("rl.")}
        for split, split_seeds in splits.items():
            if split == "validation" and not name.startswith("seed"):
                continue
            jobs += [(config_path, split, name, "rl", str(ckpt), play, sc, sd)
                     for sc in scenarios for sd in split_seeds]
    print(f"{len(jobs)} episodes ({len(names)} models + {len(BASELINES)} baselines, "
          f"{len(scenarios)} scenarios), {workers} worker(s)")
    if workers > 1:
        import multiprocessing as mp
        with mp.get_context("spawn").Pool(workers) as pool:
            rows = pool.map(_episode, jobs, chunksize=4)
    else:
        rows = [_episode(j) for j in jobs]
    return pd.DataFrame(rows), scenarios, seeds


def _md_table(header, rows, align) -> str:
    from atsc.eval.benchmark import _md_table as table
    return table(header, rows, align)


def _label(name: str) -> str:
    return f"RL, training seed {name[4:]}" + (" (shipped)" if name == SHIPPED else "")


def write_outputs(df, scenarios, seeds, names: List[str], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    for col in ("avg_waiting_time", "avg_queue"):
        df[col] = df[col].round(4)
    df.to_csv(out / "model_runs.csv", index=False)
    cols = scenarios + ["mean"]

    def means(split):
        part = df[df["split"] == split]
        wait = part.pivot_table(index="model", columns="scenario", values="avg_waiting_time")[scenarios]
        wait["mean"] = wait.mean(axis=1)
        return wait.loc[[m for m in list(BASELINES) + names if m in wait.index]]

    wait, val = means("benchmark"), means("validation")
    summary = wait.round(4).assign(split="benchmark")
    import pandas as pd
    summary = pd.concat([val.round(4).assign(split="validation"), summary])
    summary[["split"] + cols].to_csv(out / "model_summary.csv")

    def row(table, label, key):
        return [label] + [f"{table.loc[key, c]:.1f}" for c in cols]

    head = ["model"] + cols
    align = ["l"] + ["r"] * len(cols)
    lines = ["# Model study", "",
             "Average waiting time in seconds (lower is better), built-in simulator, the "
             "benchmark's scenarios and episode length. Written by `tools/model_study.py`.", ""]

    seed_names = [n for n in names if n.startswith("seed")]
    if seed_names:
        best = val.loc[seed_names, "mean"].idxmin()
        lines += ["## Model selection", "",
                  f"The same recipe trained {len(seed_names)} times; only the training seed "
                  f"differs. Means over the validation seeds {list(VALIDATION_SEEDS)}, which are "
                  "neither training traffic nor benchmark seeds. The model with the lowest mean "
                  f"is the shipped one: training seed {best[4:]}.", ""]
        rows = [row(val, "fixed-time", "fixed_time"), row(val, "max-pressure", "max_pressure")]
        rows += [row(val, _label(n), n) for n in seed_names]
        lines += [_md_table(head, rows, align), ""]

        lines += ["## Training-to-training variation", "",
                  f"The same models on the benchmark seeds {list(seeds)}: what a retrain of the "
                  "same recipe can give.", ""]
        rows = [row(wait, "fixed-time", "fixed_time"), row(wait, "max-pressure", "max_pressure")]
        rows += [row(wait, _label(n), n) for n in seed_names]
        sub = wait.loc[seed_names]
        rows.append(["**RL, mean of the models**"] + [f"{sub[c].mean():.1f}" for c in cols])
        rows.append(["RL, lowest to highest"] + [f"{sub[c].min():.1f}\u2013{sub[c].max():.1f}"
                                                  for c in cols])
        if len(seed_names) > 1:
            rows.append(["RL, standard deviation"] + [f"{sub[c].std(ddof=1):.1f}" for c in cols])
        mp_row = wait.loc["max_pressure"]
        rows.append(["models below max-pressure"] +
                    [f"{int((sub[c] < mp_row[c]).sum())} of {len(seed_names)}" for c in cols])
        lines += [_md_table(head, rows, align), ""]

    abl = [n for n in names if n in ABLATIONS]
    if abl and ABLATION_BASE in wait.index:
        lines += ["## Ablation", "",
                  f"Each row is one model trained with seed {ABLATION_BASE[4:]} and one "
                  "ingredient removed, on the benchmark seeds; the line under it is its "
                  f"difference to the full model of the same training seed. One training run "
                  "each: compare the differences with the standard deviation above before "
                  "reading anything into them.", ""]
        rows = [row(wait, f"full model, training seed {ABLATION_BASE[4:]}", ABLATION_BASE)]
        for n in abl:
            rows.append(row(wait, ABLATIONS[n][1], n))
            d = wait.loc[n] - wait.loc[ABLATION_BASE]
            rows.append(["\u00a0\u00a0difference"] +
                        [("+" if round(d[c], 1) > 0 else "\u2212" if round(d[c], 1) < 0 else "")
                         + f"{abs(d[c]):.1f}" for c in cols])
        lines += [_md_table(head, rows, align), ""]
    (out / "model_study.md").write_text("\n".join(lines), encoding="utf-8")
    print((out / "model_study.md").read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--config", default=None, help="path to config.yaml")
    ap.add_argument("--train", metavar="MODEL", help="train one study model, then exit")
    ap.add_argument("--list", action="store_true", help="list the study models")
    ap.add_argument("--models", nargs="*", default=None, help="benchmark only these models")
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--out", default=str(ROOT / "outputs" / "study"))
    args = ap.parse_args()

    catalogue = models()
    if args.list:
        for name, (ckpt, overrides) in catalogue.items():
            print(f"{name:22s} {ckpt.relative_to(ROOT)}  {'' if ckpt.exists() else '(missing)'}"
                  f"  {overrides}")
        return 0
    if args.train:
        if args.train not in catalogue:
            raise SystemExit(f"unknown model {args.train!r}; known: {', '.join(catalogue)}")
        train(args.train, args.config)
        return 0
    names = args.models if args.models is not None else list(catalogue)
    unknown = [n for n in names if n not in catalogue]
    if unknown:
        raise SystemExit(f"unknown model(s) {unknown}; known: {', '.join(catalogue)}")
    df, scenarios, seeds = benchmark(args.config, names, max(1, args.workers))
    write_outputs(df, scenarios, seeds, names, Path(args.out))
    return 0


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    raise SystemExit(main())
