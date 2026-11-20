#!/usr/bin/env python3
"""Generate the live profile assets as self-contained animated SVGs (dark and light).

Outputs (dist/ and dist/light/):
  contribution-matrix.svg, stats.svg, projects-live.svg, activity.svg
Reads real data from the GitHub GraphQL API. Standard library only.
Environment: GITHUB_USERNAME, GITHUB_TOKEN.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

FEATURED = ["DeepFake-Detection-System", "PhishShield", "Personal-Portfolio-Website"]

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { contributionCount date contributionLevel } }
      }
    }
    repositories(first: 50, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC,
                 orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        stargazerCount
        forkCount
        pushedAt
        primaryLanguage { name }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
        defaultBranchRef { target { ... on Commit { history(first: 3) { nodes { messageHeadline committedDate } } } } }
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
LANG_COLORS = ["#55E6FF", "#00D9FF", "#3A8DFF", "#7C9CFF", "#9B8CFF"]
SANS = "'Segoe UI','Helvetica Neue',Arial,sans-serif"
MONO = "'JetBrains Mono','Cascadia Code','SFMono-Regular',Consolas,'Liberation Mono',monospace"

LIGHT_MAP = {
    "030712": "f4f9fc", "071827": "e6f1f8", "05324a": "d3e8f3", "0b3350": "cfe6f2",
    "0b1a28": "dbe9f1", "0a4a60": "a5d7e8", "0a7d9c": "5bbbd6", "00b8d9": "1aa3c4",
    "55e6ff": "0a7a99", "00d9ff": "0891b2", "3a8dff": "2563eb", "eafbff": "0b2433",
    "aef3ff": "0a7a99", "91a8b8": "53697a", "7c9cff": "4a63d9", "9b8cff": "6d5fd0",
}


def lightify(svg):
    return re.sub(r"#([0-9a-fA-F]{6})\b", lambda m: "#" + LIGHT_MAP.get(m.group(1).lower(), m.group(1)), svg)


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def fetch_data(username, token):
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
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                 "User-Agent": "profile-live-assets"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=40) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError("GitHub API returned HTTP %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")))
    if result.get("errors"):
        raise RuntimeError(json.dumps(result["errors"], indent=2))
    user = (result.get("data") or {}).get("user")
    if not user:
        raise RuntimeError("GitHub did not return user '%s'." % username)
    calendar = user["contributionsCollection"]["contributionCalendar"]
    if not calendar["weeks"]:
        raise RuntimeError("The contribution calendar is empty.")
    return {
        "weeks": calendar["weeks"],
        "total": int(calendar["totalContributions"]),
        "repos": (user.get("repositories") or {}).get("nodes") or [],
        "now": now,
    }


def parse_iso(text):
    return datetime.strptime(text.replace("Z", "")[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)


def time_ago(iso, now):
    seconds = max(0, int((now - parse_iso(iso)).total_seconds()))
    if seconds < 3600:
        value, unit = max(1, seconds // 60), "min"
    elif seconds < 86400:
        value, unit = seconds // 3600, "hour"
    elif seconds < 30 * 86400:
        value, unit = seconds // 86400, "day"
    elif seconds < 365 * 86400:
        value, unit = seconds // (30 * 86400), "month"
    else:
        value, unit = seconds // (365 * 86400), "year"
    if unit == "min":
        return "%d min ago" % value
    return "%d %s%s ago" % (value, unit, "" if value == 1 else "s")


def compute_streaks(weeks):
    days = sorted((d["date"], d["contributionCount"]) for w in weeks for d in w["contributionDays"])
    longest = run = 0
    for _, count in days:
        run = run + 1 if count > 0 else 0
        longest = max(longest, run)
    index = len(days) - 1
    if index >= 0 and days[index][1] == 0:
        index -= 1  # today may simply not have contributions yet
    current = 0
    while index >= 0 and days[index][1] > 0:
        current += 1
        index -= 1
    return current, longest


def language_totals(repos):
    totals = {}
    for repo in repos:
        for edge in (repo.get("languages") or {}).get("edges") or []:
            totals[edge["node"]["name"]] = totals.get(edge["node"]["name"], 0) + edge["size"]
    grand = float(sum(totals.values())) or 1.0
    ranked = sorted(totals.items(), key=lambda item: -item[1])[:5]
    return [(name, size * 100.0 / grand) for name, size in ranked]


def latest_commits(repos, now, limit=8):
    items = []
    for repo in repos:
        if repo["name"] not in FEATURED:
            continue
        target = (repo.get("defaultBranchRef") or {}).get("target") or {}
        for node in (target.get("history") or {}).get("nodes") or []:
            message = re.sub(r"\s+", " ", node["messageHeadline"]).strip()
            if len(message) > 64:
                message = message[:61] + "..."
            items.append((node["committedDate"], repo["name"], message))
    items.sort(reverse=True)
    return ["%s | %s | %s" % (name, message, time_ago(date, now)) for date, name, message in items[:limit]]


# ----------------------------------------------------------------------------
# Shared SVG pieces
# ----------------------------------------------------------------------------
def head(width, height, label):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="%s">'
        '<defs>'
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#030712"/><stop offset="0.6" stop-color="#071827"/><stop offset="1" stop-color="#05324a"/></linearGradient>'
        '<linearGradient id="beam" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#55E6FF" stop-opacity="0"/><stop offset="0.5" stop-color="#55E6FF" stop-opacity="0.22"/><stop offset="1" stop-color="#55E6FF" stop-opacity="0"/></linearGradient>'
        '<pattern id="grid" width="30" height="30" patternUnits="userSpaceOnUse"><path d="M30 0H0V30" fill="none" stroke="#55E6FF" stroke-opacity="0.05"/></pattern>'
        '<filter id="glow" x="-50%%" y="-50%%" width="200%%" height="200%%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
        '<clipPath id="frame"><rect width="%d" height="%d" rx="16"/></clipPath>'
        '</defs>'
        '<g clip-path="url(#frame)">'
        '<rect width="%d" height="%d" fill="url(#bg)"/><rect width="%d" height="%d" fill="url(#grid)"/>'
        % (width, height, width, height, escape(label), width, height, width, height, width, height)
    )


def tail(width, height):
    return '</g><rect x="1" y="1" width="%d" height="%d" rx="15" fill="none" stroke="#55E6FF" stroke-opacity="0.2"/></svg>' % (width - 2, height - 2)


def text(x, y, size, fill, content, family=None, weight=None, anchor=None, extra=""):
    attrs = 'x="%s" y="%s" font-family="%s" font-size="%s" fill="%s"' % (x, y, family or SANS, size, fill)
    if weight:
        attrs += ' font-weight="%s"' % weight
    if anchor:
        attrs += ' text-anchor="%s"' % anchor
    return "<text %s %s>%s</text>" % (attrs, extra, escape(content))


# ----------------------------------------------------------------------------
# Contribution matrix
# ----------------------------------------------------------------------------
CELL, GAP = 16, 4
STEP = CELL + GAP
LEFT, TOP = 90, 118
WIDTH = 1200
CYCLE = 8.0


def month_labels(weeks):
    labels, last_month, last_col = [], None, -10
    for col, week in enumerate(weeks):
        days = week["contributionDays"]
        if not days:
            continue
        date = datetime.strptime(days[0]["date"], "%Y-%m-%d")
        if date.month != last_month and col - last_col >= 3:
            labels.append((col, date.strftime("%b")))
            last_month, last_col = date.month, col
        elif date.month != last_month:
            last_month = date.month
    return labels


def render_matrix(weeks, total, stamp):
    cols = len(weeks)
    grid_w = cols * STEP
    height = TOP + 7 * STEP + 58
    out = [head(WIDTH, height, "Animated contribution matrix: %d contributions in the last year" % total)]
    add = out.append
    add('<clipPath id="area"><rect x="%d" y="%d" width="%d" height="%d"/></clipPath>' % (LEFT - 4, TOP - 4, grid_w + 4, 7 * STEP + 4))
    add(text(LEFT, 50, 24, "#EAFBFF", "Contribution Activity", weight=700))
    add(text(LEFT, 76, 14, "#55E6FF", "%s contributions in the last year" % format(total, ",")))
    add(text(WIDTH - 62, 50, 12, "#91A8B8", "Updated %s UTC" % stamp, anchor="end"))
    for col, name in month_labels(weeks):
        add(text(LEFT + col * STEP, TOP - 12, 12, "#91A8B8", name))
    for row, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        add(text(LEFT - 46, TOP + row * STEP + 13, 12, "#91A8B8", name))
    for col, week in enumerate(weeks):
        for day in week["contributionDays"]:
            row = (datetime.strptime(day["date"], "%Y-%m-%d").weekday() + 1) % 7
            fill = COLORS.get(day["contributionLevel"], COLORS["NONE"])
            add('<rect x="%d" y="%d" width="%d" height="%d" rx="3" fill="%s"/>' % (LEFT + col * STEP, TOP + row * STEP, CELL, CELL, fill))
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
    ly = TOP + 7 * STEP + 22
    add(text(LEFT, ly + 12, 12, "#91A8B8", "Less"))
    for i, level in enumerate(LEVELS):
        add('<rect x="%d" y="%d" width="14" height="14" rx="3" fill="%s"/>' % (LEFT + 38 + i * 20, ly, COLORS[level]))
    add(text(LEFT + 146, ly + 12, 12, "#91A8B8", "More"))
    add(tail(WIDTH, height))
    return "".join(out)


# ----------------------------------------------------------------------------
# Streaks and languages
# ----------------------------------------------------------------------------
def render_stats(total, current, longest, langs, stamp):
    W, H = 1200, 300
    out = [head(W, H, "Streaks and top languages")]
    add = out.append
    add('<rect y="0" width="240" height="%d" fill="url(#beam)"><animate attributeName="x" from="-240" to="1200" dur="9s" repeatCount="indefinite"/></rect>' % H)
    add(text(60, 56, 12, "#91A8B8", "STREAKS", family=MONO, extra='letter-spacing="3"'))
    metrics = [("Current streak", str(current), "days"), ("Longest streak", str(longest), "days"), ("Contributions", format(total, ","), "last 12 months")]
    for i, (label, value, unit) in enumerate(metrics):
        x = 60 + i * 190
        add('<g opacity="1"><animate attributeName="opacity" keyTimes="0;%.3f;1" values="0;0;1" dur="%.1fs" fill="freeze"/>' % (0.2 * i / (1.0 + 0.2 * i), 1.0 + 0.2 * i))
        add(text(x, 150, 46, "#55E6FF", value, weight=700, extra='filter="url(#glow)"'))
        add(text(x, 184, 14, "#EAFBFF", label, weight=600))
        add(text(x, 206, 12, "#91A8B8", unit))
        add("</g>")
    add('<rect x="630" y="40" width="1.5" height="220" fill="#55E6FF" fill-opacity="0.2"/>')
    add(text(664, 56, 12, "#91A8B8", "TOP LANGUAGES", family=MONO, extra='letter-spacing="3"'))
    if not langs:
        add(text(664, 120, 15, "#91A8B8", "No language data yet."))
    for i, (name, pct) in enumerate(langs):
        y = 96 + i * 38
        width = max(3.0, pct / 100.0 * 270)
        color = LANG_COLORS[i % len(LANG_COLORS)]
        delay = 0.2 * i
        dur = 2.4
        add(text(664, y + 5, 14, "#EAFBFF", name))
        add('<rect x="800" y="%d" width="270" height="10" rx="5" fill="#0b1a28"/>' % (y - 5))
        add('<rect x="800" y="%d" width="%.1f" height="10" rx="5" fill="%s" filter="url(#glow)">'
            '<animate attributeName="width" keyTimes="0;%.3f;%.3f;1" values="0;0;%.1f;%.1f" dur="%ss" fill="freeze"/></rect>'
            % (y - 5, width, color, delay / dur, (delay + 1.2) / dur, width, width, dur))
        add(text(1140, y + 5, 13, "#91A8B8", "%.1f%%" % pct, family=MONO, anchor="end"))
    add(text(60, 268, 11, "#91A8B8", "Updated %s UTC  |  streaks counted over the last 12 months" % stamp))
    add(tail(W, H))
    return "".join(out)


# ----------------------------------------------------------------------------
# Live repository stats
# ----------------------------------------------------------------------------
def render_projects(repos, now):
    W, H = 1200, 176
    out = [head(W, H, "Live repository statistics")]
    add = out.append
    add(text(40, 46, 20, "#EAFBFF", "Live Repository Stats", weight=700))
    add('<circle cx="%d" cy="40" r="4" fill="#00D9FF" filter="url(#glow)"><animate attributeName="opacity" values="1;0.25;1" dur="1.8s" repeatCount="indefinite"/></circle>' % (W - 172))
    add(text(W - 40, 45, 12, "#91A8B8", "synced from GitHub", anchor="end"))
    by_name = dict((repo["name"], repo) for repo in repos)
    for i, name in enumerate(FEATURED):
        x = 40 + i * 380
        repo = by_name.get(name)
        if i:
            add('<rect x="%d" y="72" width="1.5" height="82" fill="#55E6FF" fill-opacity="0.2"/>' % (x - 20))
        add(text(x, 88, 17, "#EAFBFF", name, weight=700))
        if not repo:
            add(text(x, 116, 13, "#91A8B8", "Not found among public repositories"))
            continue
        language = (repo.get("primaryLanguage") or {}).get("name") or "No language"
        add('<circle cx="%d" cy="110" r="5" fill="%s"/>' % (x + 5, LANG_COLORS[i % len(LANG_COLORS)]))
        add(text(x + 18, 115, 13, "#91A8B8", "%s  |  updated %s" % (language, time_ago(repo["pushedAt"], now)), family=MONO))
        add('<rect x="%d" y="128" width="82" height="26" rx="6" fill="#030712" stroke="#55E6FF" stroke-opacity="0.4"/>' % x)
        add(text(x + 41, 146, 12, "#55E6FF", "STARS %d" % repo["stargazerCount"], family=MONO, anchor="middle"))
        add('<rect x="%d" y="128" width="82" height="26" rx="6" fill="#030712" stroke="#55E6FF" stroke-opacity="0.4"/>' % (x + 94))
        add(text(x + 135, 146, 12, "#55E6FF", "FORKS %d" % repo["forkCount"], family=MONO, anchor="middle"))
    add(tail(W, H))
    return "".join(out)


# ----------------------------------------------------------------------------
# Latest-commit ticker
# ----------------------------------------------------------------------------
def render_activity(items, stamp):
    W, H = 1200, 64
    out = [head(W, H, "Latest commits ticker")]
    add = out.append
    add('<clipPath id="ticker"><rect x="236" y="0" width="948" height="%d"/></clipPath>' % H)
    add('<rect x="16" y="16" width="200" height="32" rx="8" fill="#030712" stroke="#55E6FF" stroke-opacity="0.5"/>')
    add('<circle cx="36" cy="32" r="4" fill="#00D9FF" filter="url(#glow)"><animate attributeName="opacity" values="1;0.2;1" dur="1.6s" repeatCount="indefinite"/></circle>')
    add(text(50, 37, 12, "#55E6FF", "LATEST COMMITS", family=MONO, extra='letter-spacing="2"'))
    if not items:
        items = ["No recent public commits to show yet"]
    base = "   //   ".join(items) + "   //   "
    unit = 8.4
    while len(base) * unit < 1000:
        base += base
    width = len(base) * unit
    dur = width / 55.0
    add('<g clip-path="url(#ticker)"><g>')
    add('<animateTransform attributeName="transform" type="translate" from="0 0" to="%.1f 0" dur="%.1fs" repeatCount="indefinite"/>' % (-width, dur))
    for offset in (0, 1):
        add('<text x="%.1f" y="38" font-family="%s" font-size="14" fill="#EAFBFF" textLength="%.1f" lengthAdjust="spacing" xml:space="preserve">%s</text>'
            % (236 + offset * width, MONO, width, escape(base)))
    add("</g></g>")
    add(tail(W, H))
    return "".join(out)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def write_svg(name, svg):
    ET.fromstring(svg)  # fails loudly if the SVG is not well-formed XML
    for folder, content in (("dist", svg), (os.path.join("dist", "light"), lightify(svg))):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        if os.path.getsize(path) < 800:
            raise RuntimeError("%s is unexpectedly small." % path)


def build_all(data):
    stamp = data["now"].strftime("%Y-%m-%d %H:%M")
    current, longest = compute_streaks(data["weeks"])
    return {
        "contribution-matrix.svg": render_matrix(data["weeks"], data["total"], stamp),
        "stats.svg": render_stats(data["total"], current, longest, language_totals(data["repos"]), stamp),
        "projects-live.svg": render_projects(data["repos"], data["now"]),
        "activity.svg": render_activity(latest_commits(data["repos"], data["now"]), stamp),
    }


def main():
    username = os.environ.get("GITHUB_USERNAME")
    token = os.environ.get("GITHUB_TOKEN")
    if not username or not token:
        print("GITHUB_USERNAME and GITHUB_TOKEN must be set.", file=sys.stderr)
        return 1
    data = fetch_data(username, token)
    for name, svg in build_all(data).items():
        write_svg(name, svg)
        print("generated %s (+ light variant)" % name)
    current, longest = compute_streaks(data["weeks"])
    print("contributions=%d current_streak=%d longest_streak=%d repos=%d" % (data["total"], current, longest, len(data["repos"])))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:  # noqa: BLE001
        print("ERROR: %s" % error, file=sys.stderr)
        sys.exit(1)
