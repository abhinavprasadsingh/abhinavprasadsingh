import os
import json
import math
import urllib.request
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

USERNAME = os.environ["GITHUB_USERNAME"]
TOKEN = os.environ["GITHUB_TOKEN"]
OUTPUT = "dist/contribution-matrix.gif"

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
            contributionLevel
          }
        }
      }
    }
  }
}
"""

now = datetime.now(timezone.utc)
start = now - timedelta(days=365)

payload = {
    "query": QUERY,
    "variables": {
        "login": USERNAME,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now.isoformat().replace("+00:00", "Z")
    }
}

request = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Abhinav-Premium-Matrix"
    },
    method="POST"
)

with urllib.request.urlopen(request, timeout=30) as response:
    result = json.loads(response.read().decode("utf-8"))

if result.get("errors"):
    raise RuntimeError(json.dumps(result["errors"], indent=2))

user = result.get("data", {}).get("user")
if not user:
    raise RuntimeError("GitHub did not return the requested user.")

calendar = user["contributionsCollection"]["contributionCalendar"]
weeks = calendar["weeks"]
total = calendar["totalContributions"]

# CYAN COLOR SYSTEM
COLORS = {
    "NONE": (10, 24, 35),
    "FIRST_QUARTILE": (8, 62, 79),
    "SECOND_QUARTILE": (0, 112, 145),
    "THIRD_QUARTILE": (0, 174, 203),
    "FOURTH_QUARTILE": (72, 232, 255)
}

CELL = 13
GAP = 5
STEP = CELL + GAP
LEFT = 68
TOP = 79

WIDTH = LEFT + len(weeks) * STEP + 35
HEIGHT = 220

try:
    title_font = ImageFont.truetype("DejaVuSans.ttf", 20)
    body_font = ImageFont.truetype("DejaVuSans.ttf", 11)
except OSError:
    title_font = ImageFont.load_default()
    body_font = ImageFont.load_default()

grid = []

for week_index, week in enumerate(weeks):
    for day_index, day in enumerate(week["contributionDays"]):
        grid.append({
            "x": LEFT + week_index * STEP,
            "y": TOP + day_index * STEP,
            "level": day["contributionLevel"],
            "count": day["contributionCount"]
        })

frames = []
FRAME_COUNT = 20

for frame_index in range(FRAME_COUNT):
    frame = Image.new("RGB", (WIDTH, HEIGHT), (3, 7, 18))
    draw = ImageDraw.Draw(frame)

    # TITLE
    draw.text(
        (LEFT, 22),
        "CONTRIBUTION MATRIX",
        font=title_font,
        fill=(226, 250, 255)
    )

    draw.text(
        (LEFT, 51),
        f"{total:,} contributions in the last year",
        font=body_font,
        fill=(81, 195, 218)
    )

    # DAY LABELS
    for label, day_index in [
        ("MON", 1),
        ("WED", 3),
        ("FRI", 5)
    ]:
        y = TOP + day_index * STEP + 1
        draw.text(
            (17, y),
            label,
            font=body_font,
            fill=(91, 132, 148)
        )

    # MOVING CYAN SCANNER
    scan_position = (
        frame_index / FRAME_COUNT
    ) * (len(weeks) * STEP)

    for item in grid:
        x = item["x"]
        y = item["y"]

        color = COLORS.get(
            item["level"],
            COLORS["NONE"]
        )

        distance = abs((x - LEFT) - scan_position)
        distance = min(
            distance,
            len(weeks) * STEP - distance
        )

        if distance < 58:
            boost = int((1 - distance / 58) * 75)
            color = tuple(
                min(255, channel + boost)
                for channel in color
            )

        draw.rounded_rectangle(
            (x, y, x + CELL, y + CELL),
            radius=3,
            fill=color
        )

    # ANIMATED STATUS LIGHT
    pulse = 150 + int(
        75 * (1 + math.sin(frame_index * 0.65)) / 2
    )

    draw.ellipse(
        (WIDTH - 34, 29, WIDTH - 23, 40),
        fill=(0, pulse, min(255, pulse + 30))
    )

    # LEGEND
    legend_y = TOP + 7 * STEP + 10

    draw.text(
        (LEFT, legend_y),
        "LESS",
        font=body_font,
        fill=(91, 132, 148)
    )

    levels = [
        "NONE",
        "FIRST_QUARTILE",
        "SECOND_QUARTILE",
        "THIRD_QUARTILE",
        "FOURTH_QUARTILE"
    ]

    for index, level in enumerate(levels):
        x = LEFT + 38 + index * 19

        draw.rounded_rectangle(
            (x, legend_y, x + 12, legend_y + 12),
            radius=3,
            fill=COLORS[level]
        )

    draw.text(
        (LEFT + 145, legend_y),
        "MORE",
        font=body_font,
        fill=(91, 132, 148)
    )

    frames.append(frame)

os.makedirs("dist", exist_ok=True)

frames[0].save(
    OUTPUT,
    save_all=True,
    append_images=frames[1:],
    duration=140,
    loop=0,
    optimize=True,
    disposal=2
)

if not os.path.exists(OUTPUT) or os.path.getsize(OUTPUT) == 0:
    raise RuntimeError("Contribution matrix GIF was not created.")

print("Contribution matrix generated successfully.")
print(f"Contributions: {total}")
print(f"Weeks: {len(weeks)}")
print(f"GIF size: {os.path.getsize(OUTPUT)} bytes")