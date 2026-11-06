#!/usr/bin/env python3
"""Generate an animated JARVIS-style contribution matrix as a self-contained SVG.

Reads the real GitHub contribution calendar through the GraphQL API.
Environment: GITHUB_USERNAME, GITHUB_TOKEN. Standard library only.
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET

OUTPUT = os.path.join("dist", "contribution-matrix.svg")

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date contributionLevel } }
      }
    }
  }
}
"""

COLORS = {
    "NONE": "#0b1a28",
    "FIRST_QUARTILE": "#0a4a60",
    "SECOND_QUARTILE": "#0a7d9c",
    "THIRD_QUARTILE": "#00b8d9",
    "FOURTH_QUARTILE": "#55e6ff",
}
LEVELS = list(COLORS.keys())
MONO = "'JetBrains Mono','Cascadia Code','SFMono-Regular',Consolas,'Liberation Mono',monospace"

CELL, GAP = 16, 4
STEP = CELL + GAP
LEFT, TOP = 90, 118
WIDTH = 1200
CYCLE = 8.0


def fetch_calendar(username, token):
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now - timedelta(days=365)
    payload = {
        "query": QUERY,
        "variables": {
            "login": username,
            "from": start.isoformat().replace("+00:00", "Z"),
            "to": now.isoformat().replace("+00:00", "Z"),
        },
    }
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "User-Agent": "profile-contribution-matrix",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("GitHub API returned HTTP %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")))
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"], indent=2))
    user = (result.get("data") or {}).get("user")
    if not user:
        raise RuntimeError("GitHub did not return user '%s'." % username)
    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks = calendar["weeks"]
    if not weeks:
        raise RuntimeError("The contribution calendar is empty.")
    return weeks, int(calendar["totalContributions"])


def month_labels(weeks):
    labels, last_month, last_col = [], None, -10
    for col, week in enumerate(weeks):
        days = week["contributionDays"]
        if not days:
            continue
        date = datetime.strptime(days[0]["date"], "%Y-%m-%d")
        if date.month != last_month and col - last_col >= 3:
            labels.append((col, date.strftime("%b").upper()))
            last_month, last_col = date.month, col
        elif date.month != last_month:
            last_month = date.month
    return labels


def render_svg(weeks, total, stamp):
    cols = len(weeks)
    grid_w = cols * STEP
    height = TOP + 7 * STEP + 62
    out = []
    add = out.append
    add('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" '
        'aria-label="Animated contribution matrix: %d contributions in the last year">' % (WIDTH, height, WIDTH, height, total))
    add("""<defs>
<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#030712"/><stop offset="0.6" stop-color="#071827"/><stop offset="1" stop-color="#05324a"/></linearGradient>
<linearGradient id="beam" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#55E6FF" stop-opacity="0"/><stop offset="0.5" stop-color="#55E6FF" stop-opacity="0.22"/><stop offset="1" stop-color="#55E6FF" stop-opacity="0"/></linearGradient>
<pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#55E6FF" stroke-opacity="0.05"/></pattern>
<filter id="glow" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
<clipPath id="frame"><rect width="%d" height="%d" rx="16"/></clipPath>
<clipPath id="area"><rect x="%d" y="%d" width="%d" height="%d"/></clipPath>
</defs>""" % (WIDTH, height, LEFT - 4, TOP - 4, grid_w + 4, 7 * STEP + 4))
    add('<g clip-path="url(#frame)">')
    add('<rect width="%d" height="%d" fill="url(#bg)"/><rect width="%d" height="%d" fill="url(#grid)"/>' % (WIDTH, height, WIDTH, height))
    add('<rect x="1" y="1" width="%d" height="%d" rx="15" fill="none" stroke="#55E6FF" stroke-opacity="0.2"/>' % (WIDTH - 2, height - 2))

    # HUD corner brackets
    add('<g fill="none" stroke="#55E6FF" stroke-width="2" stroke-opacity="0.7">'
        '<path d="M18 44 V18 H44"/><path d="M%d 44 V18 H%d"/><path d="M18 %d V%d H44"/><path d="M%d %d V%d H%d"/>'
        '<animate attributeName="stroke-opacity" values="0.4;0.9;0.4" dur="4s" repeatCount="indefinite"/></g>'
        % (WIDTH - 18, WIDTH - 44, height - 44, height - 18, WIDTH - 18, height - 44, height - 18, WIDTH - 44))

    # Title block
    add('<text x="%d" y="48" font-family="%s" font-size="20" font-weight="700" fill="#EAFBFF" letter-spacing="4">CONTRIBUTION MATRIX</text>' % (LEFT, MONO))
    add('<text x="%d" y="72" font-family="%s" font-size="13" fill="#55E6FF" letter-spacing="2">%s CONTRIBUTIONS // LAST 12 MONTHS</text>'
        % (LEFT, MONO, format(total, ",")))
    add('<circle cx="%d" cy="40" r="4" fill="#00D9FF" filter="url(#glow)"><animate attributeName="opacity" values="1;0.2;1" dur="1.8s" repeatCount="indefinite"/></circle>'
        % (WIDTH - 150))
    add('<text x="%d" y="44" text-anchor="end" font-family="%s" font-size="12" fill="#91A8B8" letter-spacing="2">LIVE DATA</text>' % (WIDTH - 62, MONO))

    # Month and weekday labels
    for col, name in month_labels(weeks):
        add('<text x="%d" y="%d" font-family="%s" font-size="11" fill="#91A8B8" letter-spacing="1">%s</text>' % (LEFT + col * STEP, TOP - 12, MONO, name))
    for row, name in ((1, "MON"), (3, "WED"), (5, "FRI")):
        add('<text x="%d" y="%d" font-family="%s" font-size="11" fill="#91A8B8" letter-spacing="1">%s</text>' % (LEFT - 44, TOP + row * STEP + 12, MONO, name))

    # Cells
    for col, week in enumerate(weeks):
        for day in week["contributionDays"]:
            row = datetime.strptime(day["date"], "%Y-%m-%d").weekday()
            row = (row + 1) % 7  # Sunday = 0
            fill = COLORS.get(day["contributionLevel"], COLORS["NONE"])
            add('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>' % (LEFT + col * STEP, TOP + row * STEP, CELL, CELL, fill))

    # Scan beam and per-column pulse (kept in sync)
    travel = grid_w + 200
    add('<g clip-path="url(#area)">')
    add('<rect y="%d" width="200" height="%d" fill="url(#beam)"><animate attributeName="x" from="%d" to="%d" dur="%ss" repeatCount="indefinite"/></rect>'
        % (TOP - 4, 7 * STEP + 4, LEFT - 100, LEFT - 100 + travel, CYCLE))
    for col in range(cols):
        f = (col * STEP + CELL / 2 + 100) / float(travel)
        key = "0;%.4f;%.4f;%.4f;1" % (f - 0.03, f, f + 0.05)
        add('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="#EAFBFF" opacity="0">'
            '<animate attributeName="opacity" keyTimes="%s" values="0;0;0.32;0;0" dur="%ss" repeatCount="indefinite"/></rect>'
            % (LEFT + col * STEP, TOP, CELL, 7 * STEP - GAP, key, CYCLE))
    add("</g>")

    # Legend
    ly = TOP + 7 * STEP + 22
    add('<text x="%d" y="%d" font-family="%s" font-size="11" fill="#91A8B8" letter-spacing="2">LESS</text>' % (LEFT, ly + 11, MONO))
    for i, level in enumerate(LEVELS):
        add('<rect x="%d" y="%d" width="14" height="14" rx="3" fill="%s"/>' % (LEFT + 48 + i * 20, ly, COLORS[level]))
    add('<text x="%d" y="%d" font-family="%s" font-size="11" fill="#91A8B8" letter-spacing="2">MORE</text>' % (LEFT + 156, ly + 11, MONO))
    add('<text x="%d" y="%d" text-anchor="end" font-family="%s" font-size="11" fill="#91A8B8" letter-spacing="2">UPDATED %s UTC</text>'
        % (WIDTH - 62, ly + 11, MONO, stamp))
    add("</g></svg>")
    return "\n".join(out)


def main():
    username = os.environ.get("GITHUB_USERNAME")
    token = os.environ.get("GITHUB_TOKEN")
    if not username or not token:
        print("GITHUB_USERNAME and GITHUB_TOKEN must be set.", file=sys.stderr)
        return 1
    weeks, total = fetch_calendar(username, token)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    svg = render_svg(weeks, total, stamp)
    ET.fromstring(svg)  # fails loudly if the SVG is not well-formed XML
    os.makedirs("dist", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(svg)
    size = os.path.getsize(OUTPUT)
    if size < 1000:
        raise RuntimeError("Generated SVG is unexpectedly small.")
    print("Contribution matrix generated: %d contributions, %d weeks, %d bytes." % (total, len(weeks), size))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print("ERROR: %s" % error, file=sys.stderr)
        sys.exit(1)
