"""两个模型的附加时延：全量两种顺序，以及四次调用拆开。"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "reports" / "latency-9b-27b.png"

# 同协议拆分，各 6 条（先丢掉 2 条预热）。全量原始记录里没有这四次的分项。
QUARTET = {
    "9B": {
        "off1": (542.9, 20.0),
        "on1": (489.7, 77.9),
        "on2": (478.4, 75.4),
        "off2": (477.4, 25.4),
        "note": "第 1 次预填充 68 ms，后三次 28 ms；解码四次都约 440 ms",
    },
    "27B": {
        "off1": (1210.9, 39.0),
        "on1": (1291.9, 86.3),
        "on2": (1220.1, 59.8),
        "off2": (1210.7, 31.2),
        "note": "另一次 4 条核对：预填充四次都约 170 ms，解码都约 1030 ms",
    },
}
ORDER = ("off1", "on1", "on2", "off2")
ORDER_LABEL = ("第1次\n无关", "第1次\n加保护", "第2次\n加保护", "第2次\n无关")


def load(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def mean(rows, key):
    return sum(row[key] for row in rows) / len(rows)


def percentile(values, p):
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def setup_font():
    for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf", r"C:\Windows\Fonts\simhei.ttf"):
        if Path(path).exists():
            font_manager.fontManager.addfont(path)
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=path).get_name()
            break
    plt.rcParams["axes.unicode_minus"] = False


def style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#E6E6E6", zorder=0)
    ax.set_axisbelow(True)


def draw_totals(ax, runs):
    import numpy as np

    x = np.arange(len(runs))
    width = 0.36
    off = [mean(run["rows"], "t_off") for run in runs]
    on = [mean(run["rows"], "t_on") for run in runs]
    bars_off = ax.bar(x - width / 2, off, width, label="无保护", color="#8FA8B8", zorder=2)
    bars_on = ax.bar(x + width / 2, on, width, label="加保护", color="#3E6B8A", zorder=2)
    for bar, value, color in list(zip(bars_off, off, ["#1B2830"] * len(off))) + list(zip(bars_on, on, ["white"] * len(on))):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value - 16,
            f"{value:.0f}",
            ha="center",
            va="top",
            fontsize=10,
            color=color,
        )
    for i, (a, b) in enumerate(zip(off, on)):
        ax.text(
            x[i],
            b + 28,
            f"多 {b - a:.0f} ms（{b / a - 1:.1%}）",
            ha="center",
            va="bottom",
            fontsize=10,
            color="#1F4E79",
        )
    ax.set_xticks(x, [run["name"] for run in runs])
    ax.set_ylabel("平均耗时 (ms)")
    ax.set_ylim(0, max(on) * 1.16)
    ax.set_title("全量 1000 对：加保护比无保护多出来的时间")
    ax.legend(frameon=False, loc="upper left")
    style(ax)


def draw_orders(ax, runs):
    import numpy as np

    keys = ("delta_off_on", "delta_on_off", "delta")
    labels = ("先关后开", "先开后关", "抵消后")
    colors = ("#D4784A", "#E0B15A", "#3E7A57")
    x = np.arange(len(labels))
    width = 0.36
    for index, run in enumerate(runs):
        means = [mean(run["rows"], key) for key in keys]
        lows = [percentile([row[key] for row in run["rows"]], 0.10) for key in keys]
        highs = [percentile([row[key] for row in run["rows"]], 0.90) for key in keys]
        xpos = x + (index - 0.5) * width
        ax.bar(xpos, means, width, label=run["name"], color=("#5B7C99", "#C46B4A")[index], zorder=2)
        ax.vlines(xpos, lows, highs, color="#333333", linewidth=1.2, zorder=3)
        for px, value in zip(xpos, means):
            ax.text(px, value + (8 if value >= 0 else -16), f"{value:+.0f}", ha="center", va="bottom" if value >= 0 else "top", fontsize=10)
    ax.axhline(0, color="#444444", linewidth=0.8)
    ax.set_xticks(x, labels)
    ax.set_ylabel("附加时延 Δ (ms)")
    ax.set_title("全量 1000 对：两种顺序，以及抵消后")
    ax.legend(frameon=False)
    style(ax)
    ymin, ymax = ax.get_ylim()
    ax.set_ylim(min(ymin, -40) - 20, ymax + 35)


def draw_quartet(ax, name):
    llama = [QUARTET[name][key][0] for key in ORDER]
    rest = [QUARTET[name][key][1] for key in ORDER]
    x = range(4)
    ax.bar(x, llama, 0.62, label="模型调用", color="#4C78A8", zorder=2)
    ax.bar(x, rest, 0.62, bottom=llama, label="调用之外", color="#F2C14E", zorder=2)
    wall = [a + b for a, b in zip(llama, rest)]
    for i, (a, b) in enumerate(zip(llama, rest)):
        ax.text(i, a + b + 6, f"{a + b:.0f}\n之外 {b:.0f}", ha="center", va="bottom", fontsize=9, linespacing=1.15)
    ax.text(0.5, max(wall) * 1.22, f"先关后开 {wall[1] - wall[0]:+.0f} ms", ha="center", color="#8C3A2F", fontsize=11)
    ax.text(2.5, max(wall) * 1.22, f"先开后关 {wall[2] - wall[3]:+.0f} ms", ha="center", color="#8C3A2F", fontsize=11)
    ax.set_xticks(list(x), list(ORDER_LABEL))
    ax.set_ylabel("耗时 (ms)")
    ax.set_ylim(0, max(wall) * 1.42)
    ax.set_title(f"{name} 同一条提示词的四次调用（6 条样本）")
    ax.legend(frameon=False, loc="upper right")
    style(ax)
    ax.text(0.0, -0.22, QUARTET[name]["note"], transform=ax.transAxes, fontsize=9, color="#444444")


def main():
    setup_font()
    runs = [
        {"name": "9B", "rows": load(ROOT / "data" / "raw" / "m5-balanced.jsonl")},
        {"name": "27B", "rows": load(ROOT / "data" / "raw" / "m5-balanced-27b-1000.jsonl")},
    ]
    for run in runs:
        if len(run["rows"]) != 1000:
            raise SystemExit(f"{run['name']} rows {len(run['rows'])}")
    fig, axes = plt.subplots(2, 2, figsize=(13.6, 8.6))
    draw_totals(axes[0, 0], runs)
    draw_orders(axes[0, 1], runs)
    draw_quartet(axes[1, 0], "9B")
    draw_quartet(axes[1, 1], "27B")
    fig.suptitle("保护加在前一次还是后一次：9B 和 27B", fontsize=15, y=0.98)
    fig.text(
        0.01,
        0.01,
        "上排来自全量原始记录。每对顺序是无关、加保护、再加保护、再无关。抵消后是两种顺序的平均。竖线是 10% 到 90% 分位。下排纵轴各自缩放。",
        fontsize=9,
        color="#333333",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=160)
    print(OUT)


if __name__ == "__main__":
    main()
