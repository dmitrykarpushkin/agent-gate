#!/usr/bin/env python3
"""Run examples/demo.sh and draw part of its real output as a dark terminal picture (docs/demo.svg).

Usage: python3 scripts/render_demo_svg.py [--steps 2,3,4] [--out docs/demo.svg]
Nothing is typed by hand: the text comes from the demo run. Runs of "<check>: ok" lines are folded into one line,
and lines wider than the window are cut with an ellipsis; both are marked in the picture.
"""
import argparse, html, pathlib, re, subprocess, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
COLS, CHAR_W, LINE_H, PAD, BAR = 96, 7.8, 19, 18, 34
BG, BAR_BG, FG, DIM = "#0d1117", "#161b22", "#c9d1d9", "#6e7681"
CMD, HEAD, RED, GREEN = "#79c0ff", "#e3b341", "#ff7b72", "#3fb950"


def demo_output():
    r = subprocess.run(["sh", str(ROOT / "examples" / "demo.sh")], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        sys.exit(f"demo.sh failed with exit {r.returncode}:\n{r.stdout}{r.stderr}")
    return r.stdout


def pick(text, steps):
    out, keep = [], False
    for line in text.splitlines():
        m = re.match(r"== (\d+)\.", line)
        if m:
            keep = int(m.group(1)) in steps
        if keep:
            out.append(line)
    while out and not out[-1].strip():
        out.pop()
    folded, run = [], []
    for line in out + [None]:
        if line is not None and re.fullmatch(r"[a-z_]+: ok", line):
            run.append(line)
            continue
        folded.extend(run if len(run) < 3 else [f"# ... {len(run)} more checks: ok"])
        run = []
        if line is not None:
            folded.append(line)
    return folded


def colour(line):
    if line.startswith("== "):
        return HEAD, "bold"
    if line.startswith("$ "):
        return CMD, "normal"
    if line.startswith("# "):
        return DIM, "normal"
    if line == "(exit 0)":
        return GREEN, "bold"
    if line.startswith("(exit "):
        return RED, "bold"
    if "blocked" in line or "problem(s)" in line or line.startswith("error:"):
        return RED, "normal"
    return FG, "normal"


def render(lines, title):
    width = int(COLS * CHAR_W + 2 * PAD)
    height = int(BAR + PAD + len(lines) * LINE_H + PAD)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="ui-monospace, SFMono-Regular, Menlo, Consolas, \'Liberation Mono\', monospace" font-size="13">',
        f'<rect width="{width}" height="{height}" rx="10" fill="{BG}"/>',
        f'<path d="M0 10 a10 10 0 0 1 10 -10 h{width - 20} a10 10 0 0 1 10 10 v{BAR - 10} h-{width} z" fill="{BAR_BG}"/>',
    ]
    for i, c in enumerate(("#ff5f56", "#ffbd2e", "#27c93f")):
        parts.append(f'<circle cx="{20 + i * 20}" cy="{BAR / 2}" r="6" fill="{c}"/>')
    parts.append(f'<text x="{width / 2}" y="{BAR / 2 + 4}" fill="{DIM}" text-anchor="middle">{html.escape(title)}</text>')
    for i, line in enumerate(lines):
        if len(line) > COLS:
            line = line[: COLS - 1] + "…"
        fill, weight = colour(line)
        y = BAR + PAD + (i + 1) * LINE_H - 5
        parts.append(f'<text x="{PAD}" y="{y}" fill="{fill}" font-weight="{weight}" xml:space="preserve">{html.escape(line)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", default="2,3,4")
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo.svg"))
    a = ap.parse_args()
    steps = {int(s) for s in a.steps.split(",")}
    lines = pick(demo_output(), steps)
    pathlib.Path(a.out).write_text(render(lines, "sh examples/demo.sh  (steps " + a.steps + ")"), encoding="utf-8")
    print(f"wrote {a.out}: {len(lines)} lines")


if __name__ == "__main__":
    main()
