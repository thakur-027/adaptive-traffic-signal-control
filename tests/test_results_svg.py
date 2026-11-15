"""tools/make_results_svg.py: the README chart is drawn from the benchmark summary, and the
committed docs/assets/results.svg is what the tool draws from the committed summary."""
import csv
import importlib.util
import xml.dom.minidom
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tool():
    spec = importlib.util.spec_from_file_location("make_results_svg", ROOT / "tools" / "make_results_svg.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chart_shows_every_benchmark_mean_and_both_comparisons(cfg):
    tool = _tool()
    rows = list(csv.DictReader(open(ROOT / "outputs" / "benchmark_summary.csv", encoding="utf-8")))
    scenarios = list(cfg.eval.scenarios)
    svg = tool.build(rows, scenarios, {s: f"arrival x{i}" for i, s in enumerate(scenarios)},
                     list(cfg.eval.seeds), int(cfg.eval.episode_seconds))
    xml.dom.minidom.parseString(svg)                      # well-formed
    wait = {(r["scenario"], r["controller"]): float(r["avg_waiting_time"]) for r in rows}
    for (scenario, controller), value in wait.items():
        assert f">{value:.1f}</text>" in svg, (scenario, controller)
    for s in scenarios:
        ft = 100 * (wait[(s, "rl")] - wait[(s, "fixed_time")]) / wait[(s, "fixed_time")]
        mp = 100 * (wait[(s, "rl")] - wait[(s, "max_pressure")]) / wait[(s, "max_pressure")]
        assert f">{tool.signed(ft)}</text>" in svg
        assert f"vs max-pressure {tool.signed(mp)}</text>" in svg
    assert svg.count("<rect") >= 3 * len(scenarios)
    assert "http://www.w3.org/2000/svg" in svg and "href" not in svg       # nothing external


def test_the_committed_chart_is_up_to_date(cfg, tmp_path, monkeypatch):
    tool = _tool()
    committed = (ROOT / "docs" / "assets" / "results.svg").read_text(encoding="utf-8")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    (tmp_path / "docs" / "assets").mkdir(parents=True)
    out = tmp_path / cfg.eval.out_dir
    out.mkdir(parents=True)
    (out / "benchmark_summary.csv").write_bytes((ROOT / cfg.eval.out_dir / "benchmark_summary.csv").read_bytes())
    assert tool.main() == 0
    assert (tmp_path / "docs" / "assets" / "results.svg").read_text(encoding="utf-8") == committed
