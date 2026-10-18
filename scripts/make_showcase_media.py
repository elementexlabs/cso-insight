"""Make the README and GitHub Pages media from the project's real outputs.

The images and the walkthrough video show the built documentation site and the engineer summary page
(results/report.html) as the pipeline wrote them: no mock-ups, public data only. Needs mkdocs,
matplotlib and Pillow (the docs extras), Google Chrome for headless screenshots with a fresh empty
profile, and ffmpeg; exiftool is used when present to strip image metadata.

Writes small images, the captions file and the preview animation to docs/media/ (committed), and the
full MP4 plus the built Pages site to showcase-media/ (not committed; published with the Pages
site).
Usage: python scripts/make_showcase_media.py
"""

from __future__ import annotations

import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "media"
OUT = ROOT / "showcase-media"
PAGES = OUT / "pages"
SHOTS = OUT / "shots"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FONT = "/System/Library/Fonts/Helvetica.ttc"
SECONDS_PER_STEP = 5

# One caption per step of the walkthrough: (page, crop box in the full-page screenshot, caption).
STEPS = [
    (
        "home",
        (0, 0, 1400, 900),
        "CSO Insight checks public sewer overflow reports before they guide outfall priorities.",
    ),
    (
        "quickstart",
        (0, 0, 1400, 900),
        "One command rebuilds every result from the pinned public feed: cso-insight run --root .",
    ),
    (
        "report",
        (0, 0, 1400, 900),
        "Hold-out 2025, scored reports: a simple average beats the rainfall model.",
    ),
    (
        "report",
        (0, 800, 1400, 1700),
        "Outfalls ranked by report rows, 2022 to 2025, with intervals on the counts.",
    ),
    (
        "report",
        (0, 1600, 1400, 2500),
        "Ranked by reported volume; volumes above 10 million US gallons are set aside first.",
    ),
    (
        "report",
        (0, 2350, 1400, 3250),
        "Every quality flag is counted: 176 report rows are quarantined from fitting.",
    ),
    (
        "datamanifest",
        (0, 0, 1400, 900),
        "The source file and its hash are pinned, so every number can be rechecked.",
    ),
    (
        "results",
        (0, 0, 1400, 900),
        "The results page lists headline metrics with intervals and the cohort flow.",
    ),
]
PAGE_URLS = {
    "home": "/",
    "quickstart": "/quickstart/",
    "report": "/report/",
    "datamanifest": "/data-manifest/",
    "results": "/results/",
}


def build_site() -> None:
    if PAGES.exists():
        shutil.rmtree(PAGES)
    subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "-q", "-d", str(PAGES)], cwd=ROOT, check=True
    )
    report = PAGES / "report"
    report.mkdir(parents=True)
    shutil.copy2(ROOT / "results" / "report.html", report / "index.html")
    shutil.copytree(ROOT / "results" / "figures", report / "figures")


def serve() -> tuple[http.server.ThreadingHTTPServer, int]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(PAGES))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


def screenshots(port: int) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clean-profile-") as profile:
        for name, path in PAGE_URLS.items():
            height = 3400 if name == "report" else 2600
            subprocess.run(
                [
                    CHROME,
                    "--headless=new",
                    f"--user-data-dir={profile}",
                    "--no-first-run",
                    "--disable-extensions",
                    "--hide-scrollbars",
                    "--force-device-scale-factor=1",
                    f"--window-size=1400,{height}",
                    f"--screenshot={SHOTS / (name + '.png')}",
                    f"http://127.0.0.1:{port}{path}",
                ],
                check=True,
                capture_output=True,
                timeout=90,
            )


def captioned_frame(page: str, box: tuple[int, int, int, int], caption: str, index: int) -> Path:
    shot = Image.open(SHOTS / f"{page}.png").convert("RGB").crop(box)
    frame = Image.new("RGB", (1280, 720), "white")
    shot.thumbnail((1280, 620))
    frame.paste(shot, ((1280 - shot.width) // 2, 0))
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 620, 1280, 720), fill=(25, 45, 70))
    size = 28
    font = ImageFont.truetype(FONT, size)
    while draw.textlength(caption, font=font) > 1220 and size > 18:
        size -= 1
        font = ImageFont.truetype(FONT, size)
    width = draw.textlength(caption, font=font)
    draw.text(((1280 - width) / 2, 655), caption, font=font, fill="white")
    path = OUT / "frames" / f"frame_{index:02d}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.save(path)
    return path


def rmse_chart() -> Path:
    metrics = {
        m["name"]: m
        for m in json.loads((ROOT / "results" / "evaluation.json").read_text())["metrics"]
    }
    rows = [
        ("Mean-volume baseline", metrics["rmse_mean_volume_baseline_m3"]),
        ("Rainfall model", metrics["rmse_rainfall_model_m3"]),
    ]
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=150)
    for i, (_label, m) in enumerate(rows):
        ax.barh(i, m["value"], color=("#2f6f4f" if i == 0 else "#9c4a3c"))
        ax.errorbar(
            m["value"],
            i,
            xerr=[[m["value"] - m["ci_low"]], [m["ci_high"] - m["value"]]],
            color="black",
            capsize=4,
        )
        ax.text(m["ci_high"] + 300, i, f"{m['value']:,.0f} m³", va="center")
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlabel("Pooled RMSE, cubic metres (lower is better); bars show 95% bootstrap intervals")
    n = rows[0][1]["n"]
    ax.set_title(f"Hold-out year 2025, {n:,} scored paired report rows")
    ax.set_xlim(0, max(m["ci_high"] for _, m in rows) * 1.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()
    path = MEDIA / "rmse_comparison.png"
    fig.savefig(path)
    plt.close(fig)
    return path


def crops() -> list[Path]:
    """Hero and example images, cut from the real report and site screenshots."""
    items = [
        ("hero_report.png", "report", (180, 0, 1240, 860)),
        ("example_metrics.png", "report", (180, 300, 1220, 860)),
        ("example_ranking_rows.png", "report", (180, 840, 1220, 1650)),
        ("example_qa_flags.png", "report", (180, 2380, 1220, 3090)),
        ("example_data_manifest.png", "datamanifest", (0, 0, 1400, 900)),
    ]
    out = []
    for name, page, box in items:
        image = Image.open(SHOTS / f"{page}.png").convert("RGB").crop(box)
        path = MEDIA / name
        image.save(path, optimize=True)
        out.append(path)
    return out


def video(frames: list[Path]) -> None:
    listing = OUT / "frames" / "list.txt"
    listing.write_text(
        "".join(f"file '{f.name}'\nduration {SECONDS_PER_STEP}\n" for f in frames)
        + f"file '{frames[-1].name}'\n"
    )
    mp4 = OUT / "demo.mp4"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(listing),
            "-vf",
            "fps=10,format=yuv420p",
            "-c:v",
            "libx264",
            "-crf",
            "26",
            "-preset",
            "slow",
            "-t",
            str(len(STEPS) * SECONDS_PER_STEP),
            "-movflags",
            "+faststart",
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            str(mp4),
        ],
        check=True,
    )
    gif = MEDIA / "demo-preview.gif"
    subprocess.run(
        [
            FFMPEG,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(mp4),
            "-vf",
            "fps=1,scale=720:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse",
            "-map_metadata",
            "-1",
            str(gif),
        ],
        check=True,
    )
    cues = []
    for i, (_, _, caption) in enumerate(STEPS):
        start, end = i * SECONDS_PER_STEP, (i + 1) * SECONDS_PER_STEP
        cues.append(f"{i + 1}\n00:00:{start:02d}.000 --> 00:00:{end:02d}.000\n{caption}\n")
    (MEDIA / "demo.en.vtt").write_text("WEBVTT\n\n" + "\n".join(cues))
    shutil.copy2(frames[2], MEDIA / "demo-poster.png")
    site_media = PAGES / "media"
    site_media.mkdir(exist_ok=True)
    for f in (mp4, MEDIA / "demo.en.vtt", MEDIA / "demo-poster.png"):
        shutil.copy2(f, site_media / f.name)


def strip_metadata() -> None:
    exiftool = shutil.which("exiftool")
    images = [str(p) for p in MEDIA.glob("*") if p.suffix in {".png", ".gif"}]
    if exiftool and images:
        subprocess.run([exiftool, "-q", "-all=", "-overwrite_original", *images], check=True)


def main() -> int:
    MEDIA.mkdir(parents=True, exist_ok=True)
    build_site()
    server, port = serve()
    try:
        screenshots(port)
    finally:
        server.shutdown()
    frames = [
        captioned_frame(page, box, caption, i) for i, (page, box, caption) in enumerate(STEPS)
    ]
    rmse_chart()
    crops()
    video(frames)
    strip_metadata()
    print("media written to", MEDIA.relative_to(ROOT), "and", OUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
