"""Draws the final (Deliverable 3) architecture diagrams.

Writes docs/diagrams/solution_architecture_final.svg and technical_architecture_final.svg,
then renders each to a PNG in docs/. The Deliverable 2 diagrams (docs/*_architecture.png)
are left as they were.

Run from the repository root (needs Google Chrome for the PNGs):

    uv run --no-project --with playwright python docs/diagrams/architecture_final.py

To change a diagram, edit the boxes below and run it again. "Planned" boxes are parts we
haven't built yet (the registry and the backups); when they are built, drop planned=True.
"""

from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).parent
DOCS = HERE.parent
FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"

# Same colors as the Deliverable 2 diagrams, plus orange for time limits
STYLES = {
    "use": {
        "fill": "#E1F3EC",
        "stroke": "#0F6B4E",
        "title": "#0B4A37",
        "text": "#0F6B4E",
    },
    "build": {
        "fill": "#EEEDFB",
        "stroke": "#5446B8",
        "title": "#3A2E8C",
        "text": "#5446B8",
    },
    "neutral": {
        "fill": "#F1EEE8",
        "stroke": "#8A877F",
        "title": "#2B2B2B",
        "text": "#5C5A55",
    },
    "white": {
        "fill": "#FFFFFF",
        "stroke": "#0F6B4E",
        "title": "#0B4A37",
        "text": "#2B2B2B",
    },
}
LIMIT = {"fill": "#FDEBE4", "stroke": "#C4512E", "text": "#9A3A1C"}
LANE = {"fill": "#F9F8F5", "stroke": "#DDDAD3"}


class Svg:
    def __init__(self, width: int, height: int):
        self.width, self.height = width, height
        self.parts: list[str] = []

    def text(
        self,
        x,
        y,
        s,
        size=12.5,
        color="#2B2B2B",
        weight=400,
        anchor="start",
        italic=False,
    ):
        style = ' font-style="italic"' if italic else ""
        self.parts.append(
            f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
            f'text-anchor="{anchor}"{style}>{escape(s)}</text>'
        )

    def rect(self, x, y, w, h, fill, stroke, dashed=False, r=10, width=1.6):
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{width}"{dash}/>'
        )

    def box(
        self,
        x,
        y,
        w,
        h,
        title,
        lines=(),
        kind="neutral",
        dashed=False,
        planned=False,
        align="center",
        title_size=15.5,
        line_size=12.5,
        limits=(),
    ):
        """A rounded box: a bold title, lines under it, then orange time-limit pills."""
        st = STYLES[kind]
        self.rect(x, y, w, h, st["fill"], st["stroke"], dashed=dashed or planned)
        n = len(lines) + len(limits)
        block = title_size + 4 + len(lines) * (line_size + 5) + len(limits) * 24
        ty = y + (h - block) / 2 + title_size if align == "center" else y + 26
        tx, anchor = (x + w / 2, "middle") if align == "center" else (x + 16, "start")
        self.text(tx, ty, title, title_size, st["title"], 700, anchor)
        ly = ty + 6
        for line in lines:
            ly += line_size + 5
            self.text(tx, ly, line, line_size, st["text"], 400, anchor)
        for lim in limits:
            ly += 8
            self.pill(tx, ly, lim, anchor)
            ly += 16
        if planned:
            self.tag(x + w - 8, y - 8)
        del n

    def tag(self, right, y):
        w = 62
        self.rect(right - w, y, w, 18, "#FFFFFF", "#5446B8", r=9, width=1.3)
        self.text(right - w / 2, y + 13, "PLANNED", 10, "#5446B8", 700, "middle")

    def pill(self, x, y, s, anchor="start"):
        """An orange time-limit pill; y is its top."""
        w = len(s) * 5.75 + 28
        left = x - w / 2 if anchor == "middle" else x
        self.rect(left, y, w, 19, LIMIT["fill"], LIMIT["stroke"], r=9.5, width=1.2)
        self.clock(left + 11, y + 9.5)
        self.text(left + 20, y + 13.5, s, 11.2, LIMIT["text"], 600)

    def clock(self, cx, cy):
        self.parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="5" fill="none" stroke="{LIMIT["stroke"]}" stroke-width="1.3"/>'
            f'<path d="M{cx} {cy - 3}V{cy}H{cx + 2.5}" fill="none" stroke="{LIMIT["stroke"]}" stroke-width="1.3"/>'
        )

    def arrow(
        self,
        points,
        color="#4A4A4A",
        dashed=False,
        label=None,
        label_at=None,
        label_color=None,
        label_anchor="middle",
        both=False,
        width=1.6,
    ):
        d = "M" + " L".join(f"{x} {y}" for x, y in points)
        dash = ' stroke-dasharray="6 5"' if dashed else ""
        mid = color.strip("#")
        start = f' marker-start="url(#s{mid})"' if both else ""
        self.parts.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash}'
            f' marker-end="url(#e{mid})"{start}/>'
        )
        if label:
            lx, ly = label_at
            self.parts.append(
                f'<text x="{lx}" y="{ly}" font-size="12" fill="{label_color or color}" font-weight="600" '
                f'text-anchor="{label_anchor}" stroke="#FFFFFF" stroke-width="4" paint-order="stroke">{escape(label)}</text>'
            )

    def lane(self, x, y, w, h, title, sub, bar):
        self.rect(x, y, w, h, LANE["fill"], LANE["stroke"], r=14, width=1.3)
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="6" height="{h}" rx="3" fill="{bar}"/>'
        )
        self.text(x + 30, y + h / 2 - 4, title, 20, STYLES["neutral"]["title"], 700)
        self.text(x + 30, y + h / 2 + 18, sub, 13, STYLES["neutral"]["text"])

    def svg(self) -> str:
        colors = {"4A4A4A", "0F6B4E", "5446B8", "8A877F", "C4512E"}
        markers = "".join(
            f'<marker id="e{c}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0L10 5L0 10z" fill="#{c}"/></marker>'
            f'<marker id="s{c}" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M10 0L0 5L10 10z" fill="#{c}"/></marker>'
            for c in colors
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" '
            f'viewBox="0 0 {self.width} {self.height}" font-family="{FONT}">'
            f'<defs>{markers}</defs><rect width="100%" height="100%" fill="#FFFFFF"/>'
            + "".join(self.parts)
            + "</svg>"
        )


def legend(s: Svg, y: int, items):
    x = 35
    for kind, label in items:
        if kind == "limit":
            s.pill(x, y - 2, "time limit")
            x += 100
        elif kind == "planned":
            s.tag(x + 62, y - 1)
            x += 72
        elif kind == "assumed":
            s.arrow([(x, y + 8), (x + 40, y + 8)], "#5446B8", dashed=True)
            x += 50
        else:
            st = STYLES[kind if kind != "volume" else "neutral"]
            s.rect(
                x,
                y,
                24,
                18,
                st["fill"],
                st["stroke"],
                dashed=kind == "volume",
                r=4,
                width=1.3,
            )
            x += 32
        s.text(x, y + 14, label, 13, "#5C5A55")
        x += len(label) * 7.2 + 34


# ---------------------------------------------------------------- technical architecture


def technical() -> Svg:
    s = Svg(1520, 1340)
    s.text(
        35,
        50,
        "Eenie Meenie Movies: technical architecture (final)",
        28,
        "#2B2B2B",
        700,
    )
    s.text(
        35,
        78,
        "What runs on Jetstream2, how code gets there, how data is built, and where each time limit sits",
        15,
        "#5C5A55",
    )

    # Jetstream2 boundary
    s.rect(250, 110, 1245, 750, "none", "#5C5A55", dashed=True, r=18, width=1.5)
    s.text(
        270,
        136,
        "Jetstream2 instance · team01-app.cis240466.projects.jetstream-cloud.org",
        15,
        "#2B2B2B",
        700,
    )
    s.text(1475, 136, "firewall: only ports 80 and 443 open", 13, "#5C5A55", 600, "end")

    # Outside the instance
    s.box(
        30,
        165,
        200,
        215,
        "Browser",
        [
            "UI: HTML, CSS, JavaScript",
            "served by the app",
            "last group saved in",
            "localStorage (this device)",
        ],
        limits=["poll 1 s, give up at 60 s", "busy: wait Retry-After", "up to 4 tries"],
    )
    s.box(30, 440, 200, 80, "image.tmdb.org", ["posters, loaded by", "the browser"])
    s.arrow([(130, 380), (130, 440)])
    s.box(
        30, 560, 200, 95, "Team laptop", ["views the dashboards", "over an SSH tunnel"]
    )

    # caddy, prometheus, grafana
    s.box(
        275,
        165,
        190,
        215,
        "caddy",
        [
            ":80 and :443, the only",
            "ports open to the internet",
            "HTTPS, Let's Encrypt cert",
            "http → https (308)",
            "sends the real client IP",
        ],
        kind="use",
        limits=["app connect: 3 s"],
    )
    s.arrow([(230, 230), (275, 230)], label="HTTPS", label_at=(252, 222))
    s.box(
        275,
        420,
        190,
        110,
        "prometheus",
        ["127.0.0.1:9090", "reads /metrics every 15 s", "keeps 30 days"],
        kind="use",
    )
    s.box(
        275,
        560,
        190,
        110,
        "grafana",
        ["127.0.0.1:3000", "dashboard and the SLO:", "99% of jobs under 5 s"],
        kind="use",
    )
    s.arrow([(370, 560), (370, 530)])
    s.arrow([(230, 607), (275, 607)], dashed=True)

    # app container
    s.rect(520, 150, 465, 535, STYLES["use"]["fill"], STYLES["use"]["stroke"], r=14)
    s.text(540, 178, "app container", 18, STYLES["use"]["title"], 700)
    s.text(
        540,
        199,
        "FastAPI and the UI · 127.0.0.1:8080, reached only through caddy",
        13,
        STYLES["use"]["text"],
    )
    s.arrow([(465, 230), (520, 230)], label="HTTP", label_at=(492, 222))
    s.arrow([(465, 475), (520, 475)], label="/metrics", label_at=(492, 467), both=True)
    s.box(
        538,
        215,
        430,
        110,
        "Request guards (before any work)",
        [
            "per client IP: 5 at once, then 10 a minute → 429",
            "8 jobs already running → 503",
            "both answer with Retry-After · body over 32 KB → 413",
            "body not JSON → 415",
        ],
        kind="white",
        align="left",
        title_size=14.5,
        line_size=12.5,
    )
    s.box(
        538,
        338,
        430,
        155,
        "Endpoints (async job pattern)",
        [
            "GET /   the UI",
            "POST /recommend → 202 and a job_id",
            "GET /recommend/{job_id}/status, /results",
            "POST /events/watch · GET /movies/search",
            "GET /health, /ready, /docs",
            "GET /metrics (needs the Bearer token)",
        ],
        kind="white",
        align="left",
        title_size=14.5,
    )
    s.box(
        538,
        506,
        430,
        92,
        "Recommendation job (background thread)",
        ["embed each pick (bge-small) → search Qdrant → combine"],
        kind="white",
        align="left",
        title_size=14.5,
        limits=["finished results kept 1 h, then dropped"],
    )
    s.box(
        538,
        611,
        430,
        62,
        "Logs",
        ["JSON lines with an X-Request-ID; what people type is never logged"],
        kind="white",
        align="left",
        title_size=14.5,
        line_size=12,
    )
    s.pill(520, 697, "healthcheck /ready: every 30 s, 5 s limit, 2 min to start")

    # compose note, qdrant, ingest
    s.box(
        1040,
        150,
        200,
        120,
        "Docker Compose",
        [
            "restart: unless-stopped",
            "starts each container once",
            "what it needs is healthy",
            "(back after reboot or unshelve)",
        ],
    )
    s.box(
        1040,
        400,
        200,
        140,
        "qdrant container",
        [
            "vector database, :6333",
            "not published",
            "one collection per",
            "embedding model",
        ],
        kind="use",
        limits=["health: every 10 s, 5 s limit"],
    )
    s.arrow(
        [(968, 552), (1012, 552), (1012, 470), (1040, 470)],
        color="#0F6B4E",
        label="search",
        label_at=(1012, 574),
    )
    s.pill(1040, 556, "Qdrant client: 30 s per call")
    s.box(
        1270,
        150,
        200,
        215,
        "ingest container",
        [
            "one-shot job, then exits",
            "reads the movie Parquet",
            "embeds each movie",
            "upserts 256 at a time",
            "skips movies already in",
        ],
        kind="use",
    )
    s.arrow(
        [(1370, 365), (1370, 470), (1240, 470)],
        color="#0F6B4E",
        label="upsert",
        label_at=(1380, 420),
        label_anchor="start",
    )

    # volumes
    vols = [
        ("caddy-data", "TLS certificates"),
        ("prometheus-data", "30 days of metrics"),
        ("grafana-data", "users, settings"),
        ("logs", "app.jsonl"),
        ("models", "embedding weights"),
        ("qdrant-storage", "movie vectors"),
        ("data/clean", "Parquet, read-only"),
    ]
    for i, (name, sub) in enumerate(vols):
        s.box(275 + i * 172, 745, 160, 75, name, [sub], dashed=True, title_size=14)
    s.text(
        275,
        845,
        "Volumes (dashed) outlast the containers.",
        12.5,
        "#5C5A55",
        italic=True,
    )

    # Delivery
    s.text(30, 905, "Delivery", 19, "#2B2B2B", 700)
    y = 920
    s.box(30, y, 100, 65, "Issue")
    s.box(160, y, 100, 65, "PR")
    s.box(
        290,
        y,
        215,
        65,
        "CI · GitHub Actions",
        ["uv sync --frozen, ruff, mypy, pytest"],
        title_size=14.5,
        line_size=12,
    )
    s.box(535, y, 95, 65, "main")
    s.box(
        660,
        y,
        215,
        65,
        "Registry (GHCR)",
        ["named by commit, smoke-tested"],
        planned=True,
        title_size=14.5,
        line_size=12,
    )
    s.box(
        905,
        y,
        245,
        65,
        "Deploy on Jetstream2",
        ["today: git pull, docker compose up -d"],
        title_size=14.5,
        line_size=12,
    )
    for a, b in [(130, 160), (260, 290), (505, 535)]:
        s.arrow([(a, y + 32), (b, y + 32)])
    s.arrow([(630, y + 32), (660, y + 32)], dashed=True, color="#5446B8")
    s.arrow([(875, y + 32), (905, y + 32)], dashed=True, color="#5446B8")
    s.arrow(
        [(1027, y), (1027, 860)],
        label="ships to the instance",
        label_at=(1037, 890),
        label_anchor="start",
    )

    # Backups
    s.text(30, 1025, "Backups", 19, "#2B2B2B", 700)
    y = 1040
    s.box(
        30,
        y,
        260,
        65,
        "Qdrant snapshot",
        ["of the movie collection (qdrant-storage)"],
        planned=True,
        title_size=14.5,
        line_size=12,
    )
    s.box(
        320,
        y,
        260,
        65,
        "Copy off the instance",
        ["so losing the instance doesn't lose it"],
        planned=True,
        title_size=14.5,
        line_size=12,
    )
    s.box(
        610,
        y,
        260,
        65,
        "Restore test",
        ["into a fresh Qdrant, then check /ready"],
        planned=True,
        title_size=14.5,
        line_size=12,
    )
    s.box(
        900,
        y,
        250,
        65,
        "Rebuilt, not backed up",
        ["code (git), weights, the Parquet"],
        title_size=14.5,
        line_size=12,
    )
    s.arrow([(290, y + 32), (320, y + 32)], dashed=True, color="#5446B8")
    s.arrow([(580, y + 32), (610, y + 32)], dashed=True, color="#5446B8")

    # Measurement
    s.text(30, 1145, "Data and measurement (offline)", 19, "#2B2B2B", 700)
    y = 1160
    boxes = [
        ("Movie data", ["TMDB API + IMDb → Parquet"]),
        ("Eval set", ["MovieLens tag genome"]),
        ("Recommender code", ["embed + Qdrant"]),
        ("Eval results", ["Precision@K, Recall@K, nDCG"]),
        ("Update recommender", ["findings become issues"]),
    ]
    for i, (t, ls) in enumerate(boxes):
        s.box(
            30 + i * 230, y, 200, 65, t, ls, kind="build", title_size=14.5, line_size=12
        )
        if i:
            s.arrow([(i * 230, y + 32), (30 + i * 230, y + 32)], color="#5446B8")
    s.arrow(
        [(1050, y + 65), (1050, 1245), (14, 1245), (14, 952), (30, 952)],
        color="#5446B8",
        dashed=True,
        label="findings become new issues",
        label_at=(530, 1240),
    )

    # Time limits table
    tx, ty = 1170, 895
    s.rect(tx, ty, 322, 335, "#FFFFFF", LIMIT["stroke"], r=12, width=1.4)
    s.text(
        tx + 16,
        ty + 28,
        "Every time limit, and where it sits",
        14.5,
        LIMIT["text"],
        700,
    )
    rows = [
        ("Browser", "polls every 1 s, gives up at 60 s"),
        ("Browser", "on 429/503 waits Retry-After, 4 tries"),
        ("caddy → app", "3 s to connect (Caddy's default)"),
        ("app", "5 at once, then 10 a minute per IP"),
        ("app", "8 jobs at once; the 9th waits 5 s"),
        ("app", "finished results kept 1 hour"),
        ("app → Qdrant", "30 s per call (ingest too)"),
        ("app health", "every 30 s, 5 s limit, 2 min to start"),
        ("qdrant health", "every 10 s, 5 s limit"),
        ("prometheus", "reads /metrics every 15 s; 30 days"),
        ("SLO", "99% of jobs finish in 5 s (28 days)"),
    ]
    for i, (where, what) in enumerate(rows):
        yy = ty + 56 + i * 25.5
        s.text(tx + 16, yy, where, 12, "#2B2B2B", 700)
        s.text(tx + 108, yy, what, 12, "#5C5A55")

    legend(
        s,
        1290,
        [
            ("use", "Container"),
            ("volume", "Volume"),
            ("neutral", "External or pipeline step"),
            ("build", "Offline"),
            ("limit", ""),
            ("planned", "Not built yet"),
            ("assumed", "Planned or assumed link"),
        ],
    )
    return s


# ---------------------------------------------------------------- solution architecture


def solution() -> Svg:
    s = Svg(1520, 1250)
    s.text(
        35, 50, "Eenie Meenie Movies: solution architecture (final)", 28, "#2B2B2B", 700
    )
    s.text(
        35,
        78,
        "The process people follow, how it executes, what we measure, how the model is built, and what is stored",
        15,
        "#5C5A55",
    )
    X0, W, GAP = 215, 160, 20

    def col(i, w=W, gap=GAP):
        return X0 + i * (w + gap)

    # Process
    s.lane(25, 115, 1465, 185, "Process", "what people do", "#0F6B4E")
    y = 155
    steps = [
        ("Choose mode", ["a group of 2 to 6,", "or just me"], False),
        ("Setup", ["names, or", "“use last group”"], True),
        ("Write picks", ["in secret, pass the", "device; or no preference"], False),
        ("Everyone’s sealed", ["change a pick: the", "box starts empty"], True),
        ("Find our movie", ["one job for the group"], False),
        ("View results", ["top pick, also close,", "fit per person"], False),
        ("Watch or share", ["“we’re watching”,", "Share or Copy"], False),
    ]
    for i, (t, ls, opt) in enumerate(steps):
        s.box(
            col(i),
            y,
            W,
            110,
            t,
            ls,
            kind="use",
            dashed=opt,
            title_size=15,
            line_size=12.5,
            limits=["busy: count down, retry"] if i == 4 else [],
        )
        if i:
            s.arrow([(col(i) - GAP, y + 55), (col(i), y + 55)])
    s.arrow(
        [(col(0) + 80, y), (col(0) + 80, 138), (col(2) + 80, 138), (col(2) + 80, y)],
        dashed=True,
    )
    s.text(col(1) + 80, 133, "solo skips setup", 12, "#5C5A55", anchor="middle")
    s.text(
        col(3) + 80,
        288,
        "dashed = group only",
        11.5,
        "#5C5A55",
        anchor="middle",
        italic=True,
    )

    # Execution
    s.lane(25, 320, 1465, 185, "Execution", "what runs, in order", "#0F6B4E")
    y = 360
    w6, g6 = 194, 19
    ex = [
        (
            "Browser UI",
            ["sends the picks, then", "asks for the status"],
            ["every 1 s, up to 60 s"],
        ),
        ("caddy", ["HTTPS at the instance’s", "name; real client IP"], []),
        (
            "Request guards",
            ["rate limit, 8 jobs at", "once, body size"],
            ["5 at once, then 10/min"],
        ),
        ("Job thread", ["embed each pick,", "combine the scores"], []),
        ("Qdrant search", ["nearest movies", "for each pick"], ["30 s per call"]),
        ("Results", ["kept in memory"], ["dropped after 1 h"]),
    ]
    for i, (t, ls, lim) in enumerate(ex):
        x = X0 + i * (w6 + g6)
        s.box(
            x, y, w6, 110, t, ls, kind="use", title_size=15, line_size=12.5, limits=lim
        )
        if i:
            s.arrow([(x - g6, y + 55), (x, y + 55)])
    s.arrow(
        [(col(4) + 80, 265), (col(4) + 80, 300), (X0 + 97, 300), (X0 + 97, y)],
        color="#0F6B4E",
    )

    # Monitor
    s.lane(25, 525, 1465, 185, "Monitor", "what we measure", "#8A877F")
    y = 565
    mon = [
        ("Request logs", ["route, status, time,", "X-Request-ID"]),
        ("Job stats", ["number of picks,", "duration, outcome"]),
        ("Watch clicks", ["which movie the", "group chose"]),
        ("/metrics", ["counts and timings,", "needs a token"]),
        ("Prometheus", ["reads it every 15 s,", "keeps 30 days"]),
        ("Grafana", ["dashboard, SLO: 99%", "of jobs under 5 s"]),
    ]
    for i, (t, ls) in enumerate(mon):
        x = X0 + i * (w6 + g6)
        s.box(x, y, w6, 110, t, ls, title_size=15, line_size=12.5)
        if i >= 4:
            s.arrow([(x - g6, y + 55), (x, y + 55)])
    s.text(X0, 700, "What people type is never logged.", 12, "#5C5A55", italic=True)

    # Build
    s.lane(25, 730, 1465, 185, "Build", "model, data, evaluation", "#5446B8")
    y = 770
    bl = [
        ("Movie data", ["TMDB API + IMDb", "→ Parquet"]),
        ("Ingest", ["embed with bge-small,", "store in Qdrant"]),
        ("Eval set", ["from the MovieLens", "tag genome"]),
        ("Baseline", ["BM25"]),
        ("Measure", ["Precision@K, Recall@K,", "nDCG"]),
        ("Vector search", ["model in use"]),
    ]
    for i, (t, ls) in enumerate(bl):
        x = X0 + i * (w6 + g6)
        s.box(x, y, w6, 110, t, ls, kind="build", title_size=15, line_size=12.5)
        if i:
            s.arrow([(x - g6, y + 55), (x, y + 55)], color="#5446B8")
    xv = X0 + 5 * (w6 + g6) + w6
    s.arrow(
        [
            (xv, y + 55),
            (xv + 18, y + 55),
            (xv + 18, 345),
            (X0 + 3 * (w6 + g6) + 97, 345),
            (X0 + 3 * (w6 + g6) + 97, 360),
        ],
        color="#5446B8",
        label="powers the recommendations",
        label_at=(xv + 8, 340),
        label_anchor="end",
    )

    # State
    s.lane(25, 935, 1465, 255, "State", "what is stored, and where", "#8A877F")
    w5, g5 = 236, 20
    st = [
        (
            "Movie vectors",
            ["Qdrant, qdrant-storage volume", "backup: snapshots (planned)"],
            False,
        ),
        ("Model weights", ["models volume", "(downloaded again if lost)"], False),
        ("Logs", ["app.jsonl, logs volume"], False),
        ("Metrics history", ["prometheus-data, 30 days"], False),
        ("TLS certificates", ["caddy-data volume"], False),
        ("Jobs and results", ["app memory, 1 hour;", "lost on restart"], False),
        ("Config and secrets", [".env on the instance,", "never in git"], False),
        ("Last group", ["browser localStorage,", "this device only"], False),
        ("Code and decisions", ["GitHub: issues, PRs, docs"], False),
        ("Images", ["GitHub Container Registry"], True),
    ]
    for i, (t, ls, planned) in enumerate(st):
        x = X0 + (i % 5) * (w5 + g5)
        yy = 960 + (i // 5) * 113
        s.box(x, yy, w5, 95, t, ls, dashed=True, title_size=15, line_size=12.5)
        if planned:
            s.tag(x + w5 - 8, yy - 8)

    legend(
        s,
        1212,
        [
            ("use", "Process and execution"),
            ("neutral", "Measured or stored"),
            ("build", "Build"),
            ("limit", ""),
            ("planned", "Not built yet"),
        ],
    )
    return s


def render(name: str, svg: Svg) -> None:
    src = HERE / f"{name}.svg"
    src.write_text(svg.svg())
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        page = browser.new_page(
            viewport={"width": svg.width, "height": svg.height}, device_scale_factor=2
        )
        page.goto(src.resolve().as_uri())
        page.screenshot(path=str(DOCS / f"{name}.png"))
        browser.close()
    print("wrote", src, "and", DOCS / f"{name}.png")


if __name__ == "__main__":
    render("technical_architecture_final", technical())
    render("solution_architecture_final", solution())
