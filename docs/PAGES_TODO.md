# GitHub Pages: what makes the "Try it live" links work

The README links https://elementexlabs.github.io/cso-insight/ (documentation and engineer summary) and
https://elementexlabs.github.io/cso-insight/media/demo.mp4 (the walkthrough). They go live when Pages is enabled.

1. Run `python scripts/make_showcase_media.py`. It builds the site into `showcase-media/pages/`, adds the engineer
   summary under `report/` and the walkthrough under `media/`.
2. Publish `showcase-media/pages/` as the site (for example to the `gh-pages` branch) and enable Pages from it.
3. Open both links and the captions file before announcing them.
