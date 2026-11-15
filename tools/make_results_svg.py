#!/usr/bin/env python3
"""Draw docs/assets/results.svg from outputs/benchmark_summary.csv.

    python tools/make_results_svg.py

The chart of the README: average waiting time per vehicle for the three controllers at
every demand level of the benchmark, the RL change against fixed-time in a chip above each
group and the RL change against max-pressure under it. Every figure in it is read from the
benchmark summary, so rerun this after `python run.py eval`.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

W, H = 1200, 452
LEFT, RIGHT, BASE, TOP = 96, 1160, 344, 120            # plot area; BASE is the 0 s line
CONTROLLERS = ("fixed_time", "max_pressure", "rl")
FILL = {"fixed_time": "#475569", "max_pressure": "#38bdf8", "rl": "url(#rlbar)"}
NAME = {"fixed_time": "fixed-time", "max_pressure": "max-pressure", "rl": "RL agents"}
MINUS = "−"


def signed(pct: float) -> str:
    return (MINUS if pct < 0 else "+") + f"{abs(pct):.1f} %"


def build(rows, scenarios, scales, seeds, episode_s) -> str:
    wait = {(r["scenario"], r["controller"]): float(r["avg_waiting_time"]) for r in rows}
    top_value = max(wait.values())
    step = 30 if top_value <= 150 else 50
    axis_max = step * (int(top_value // step) + 1)
    px = (BASE - TOP) / axis_max
    n = len(scenarios)
    pitch = (RIGHT - LEFT) / n
    bar, gap = 48, 8
    cut_ft = {s: 100 * (wait[(s, "rl")] - wait[(s, "fixed_time")]) / wait[(s, "fixed_time")] for s in scenarios}
    cut_mp = {s: 100 * (wait[(s, "rl")] - wait[(s, "max_pressure")]) / wait[(s, "max_pressure")] for s in scenarios}
    first, last = scenarios[0], max(scenarios, key=lambda s: wait[(s, "fixed_time")])
    label = (f"Average waiting time per vehicle on a 2x2 grid, {episode_s}-second episodes, mean of "
             f"{len(seeds)} seeds. Fixed-time, max-pressure and the RL agents across {n} demand "
             f"levels. Against fixed-time the agents cut waiting time by {abs(cut_ft[first]):.0f} "
             f"percent at {first} demand and {abs(cut_ft[last]):.0f} percent at {last}, where "
             f"fixed-time reaches {wait[(last, 'fixed_time')]:.1f} seconds and the agents "
             f"{wait[(last, 'rl')]:.1f}. Against max-pressure the change is "
             + ", ".join(f"{signed(cut_mp[s]).replace(MINUS, 'minus ').replace('+', 'plus ')} at {s}"
                         for s in scenarios) + ".")
    o = [f'<?xml version="1.0" encoding="UTF-8"?>',
         f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}"',
         f'     role="img" aria-label="{label}">',
         '  <title>Measured benchmark: waiting time by controller and demand</title>',
         '  <defs>',
         '    <linearGradient id="abg" x1="0" y1="0" x2="1" y2="1">',
         '      <stop offset="0" stop-color="#0a1020"/>',
         '      <stop offset="0.55" stop-color="#0f1a33"/>',
         '      <stop offset="1" stop-color="#0b1322"/>',
         '    </linearGradient>',
         '    <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">',
         '      <path d="M40 0H0V40" fill="none" stroke="#ffffff" stroke-opacity="0.04"/>',
         '    </pattern>',
         '    <linearGradient id="rlbar" x1="0" y1="0" x2="0" y2="1">',
         '      <stop offset="0" stop-color="#4ade80"/>',
         '      <stop offset="1" stop-color="#16a34a"/>',
         '    </linearGradient>',
         '  </defs>',
         f'  <rect width="{W}" height="{H}" rx="20" fill="url(#abg)"/>',
         f'  <rect width="{W}" height="{H}" rx="20" fill="url(#grid)"/>',
         f'  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="20" fill="none" stroke="#ffffff" stroke-opacity="0.09"/>',
         '  <g font-family="Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif">',
         '  <rect x="40" y="40" width="4" height="14" rx="2" fill="#34d399"/>',
         '  <text x="54" y="52" font-size="11.5" font-weight="700" fill="#93a3c4" letter-spacing="0.6">BENCHMARK · AVERAGE WAITING TIME PER VEHICLE</text>']
    x = RIGHT
    for c in reversed(CONTROLLERS):                       # legend, right-aligned
        width = 6.0 * len(NAME[c])
        x -= width
        o.append(f'  <text x="{x:.0f}" y="51" font-size="10" fill="#9fb0d0">{NAME[c]}</text>')
        x -= 17
        o.append(f'  <rect x="{x:.0f}" y="41" width="11" height="11" rx="3" fill="{FILL[c]}"/>')
        x -= 20
    seed_text = f"seeds {seeds[0]}–{seeds[-1]}" if seeds == list(range(seeds[0], seeds[-1] + 1)) \
        else "seeds " + ", ".join(map(str, seeds))
    o.append(f'  <text x="40" y="74" font-size="10" fill="#7f90b3">2 × 2 grid · {episode_s} s episodes · '
             f'mean of {len(seeds)} runs ({seed_text}) · lower is better · chips: RL against fixed-time</text>')
    for v in range(0, axis_max + 1, step):
        y = BASE - v * px
        if v:
            o.append(f'  <path d="M{LEFT} {y:.1f}H{RIGHT}" stroke="#ffffff" stroke-opacity="0.06" stroke-width="1"/>')
        o.append(f'  <text x="{LEFT - 12}" y="{y + 3.5:.1f}" font-size="9.5" fill="#7f90b3" text-anchor="end">'
                 f'{v}{" s" if v == axis_max else ""}</text>')
    o.append(f'  <path d="M{LEFT} {BASE}H{RIGHT}" stroke="#2c3d5f" stroke-width="1.4"/>')
    for i, s in enumerate(scenarios):
        cx = LEFT + pitch * (i + 0.5)
        tallest = max(wait[(s, c)] for c in CONTROLLERS)
        o.append(f'  <path d="M{cx:.0f} 112V{BASE - tallest * px - 22:.0f}" stroke="#22c55e" stroke-opacity="0.22" '
                 'stroke-width="1" stroke-dasharray="2 5"/>')
        o.append(f'  <rect x="{cx - 44:.1f}" y="84" width="88" height="26" rx="9" fill="#22c55e" fill-opacity="0.13" '
                 'stroke="#22c55e" stroke-opacity="0.4"/>')
        o.append(f'  <text x="{cx:.0f}" y="103" font-size="14.5" font-weight="700" fill="#34d399" '
                 f'text-anchor="middle">{signed(cut_ft[s])}</text>')
        for k, c in enumerate(CONTROLLERS):
            v = wait[(s, c)]
            bx = cx + (k - 1) * (bar + gap) - bar / 2
            o.append(f'  <rect x="{bx:.1f}" y="{BASE - v * px:.1f}" width="{bar}" height="{v * px:.1f}" rx="4" fill="{FILL[c]}"/>')
            style = 'font-weight="700" fill="#f1f5fd"' if c == "rl" else 'fill="#9fb0d0"'
            o.append(f'  <text x="{bx + bar / 2:.1f}" y="{BASE - v * px - 7:.1f}" font-size="9.5" {style} '
                     f'text-anchor="middle">{v:.1f}</text>')
        o.append(f'  <text x="{cx:.0f}" y="362" font-size="12" font-weight="700" fill="#f1f5fd" text-anchor="middle">{s}</text>')
        o.append(f'  <text x="{cx:.0f}" y="376" font-size="9" fill="#7f90b3" text-anchor="middle">{scales[s]}</text>')
        better = cut_mp[s] < 0
        o.append(f'  <text x="{cx:.0f}" y="396" font-size="10" fill="{"#34d399" if better else "#fbbf24"}" '
                 f'text-anchor="middle">vs max-pressure {signed(cut_mp[s])}</text>')
    o.append(f'  <text x="{W / 2:.0f}" y="428" font-size="10" fill="#7f90b3" text-anchor="middle">'
             'Fixed-time is close to saturation at high and rush demand, so max-pressure is the fairer '
             'yardstick: the line under each group is the RL change against it.</text>')
    o += ['  </g>', '</svg>', '']
    return "\n".join(o)


def main() -> int:
    from atsc.config import load_config
    cfg = load_config()
    rows = list(csv.DictReader(open(ROOT / cfg.eval.out_dir / "benchmark_summary.csv", encoding="utf-8")))
    scenarios = [s for s in cfg.eval.scenarios if any(r["scenario"] == s for r in rows)]
    scales = {}
    for s in scenarios:
        spec = cfg.scenarios[s]
        scale = float(spec["arrival_scale"])
        scales[s] = (f"arrival ×{scale * 0.6:.2f} → ×{scale * 1.6:.2f} → ×{scale * 0.6:.2f}"
                     if spec.get("time_varying") else f"arrival ×{scale:.2f}")
    svg = build(rows, scenarios, scales, [int(x) for x in cfg.eval.seeds], int(cfg.eval.episode_seconds))
    out = ROOT / "docs" / "assets" / "results.svg"
    out.write_text(svg, encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
