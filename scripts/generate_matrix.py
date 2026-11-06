import os
import json
import urllib.request
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont

USERNAME = os.environ["GITHUB_USERNAME"]
TOKEN = os.environ["GITHUB_TOKEN"]
OUTPUT = "dist/contribution-matrix.gif"

query = """
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
    "query": query,
    "variables": {
        "login": USERNAME,
        "from": start.isoformat(),
        "to": now.isoformat()
    }
}

request = urllib.request.Request(
    "https://api.github.com/graphql",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "Abhinav-Premium-Contribution-Matrix"
    },
    method="POST"
)

with urllib.request.urlopen(request, timeout=30) as response:
    result = json.loads(response.read().decode("utf-8"))

if result.get("errors"):
    raise RuntimeError(json.dumps(result["errors"], indent=2))

calendar = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
weeks = calendar["weeks"]
total = calendar["totalContributions"]

# Contribution intensity colors
colors = {
    "NONE": (12, 27, 39),
    "FIRST_QUARTILE": (9, 65, 83),
    "SECOND_QUARTILE": (0, 119, 151),
    "THIRD_QUARTILE": (0, 181, 207),
    "FOURTH_QUARTILE": (75, 235, 255)
}

cell = 13
gap = 5
step = cell + gap
left = 65
top = 75
width = left + len(weeks) * step + 35
height = 235

try:
    title_font = ImageFont.truetype("DejaVuSans.ttf", 21)
    small_font = ImageFont.truetype("DejaVuSans.ttf", 11)
except OSError:
    title_font = ImageFont.load_default()
    small_font = ImageFont.load_default()

# Build the contribution grid
grid = []
for week_index, week in enumerate(weeks):
    for day_index, day in enumerate(week["contributionDays"]):
        grid.append({
            "x": left + week_index * step,
            "y": top + day_index * step,
            "level": day["contributionLevel"],
            "count": day["contributionCount"],
            "date": day["date"]
        })

frames = []
frame_count = 18

for frame_index in range(frame_count):
    base = Image.new("RGB", (width, height), (3, 7, 18))
    draw = ImageDraw.Draw(base)

    draw.text(
        (left, 22),
        "CONTRIBUTION MATRIX",
        font=title_font,
        fill=(224, 250, 255)
    )

    draw.text(
        (left, 49),
        f"{total:,} contributions in the last year",
        font=small_font,
        fill=(75, 190, 210)
    )

    draw.text((12, top + 2, 48, top + 14), "MON", font=small_font, fill=(91, 130, 145))
    draw.text((12, top + step * 3 + 2, 48, top + step * 3 + 14), "WED", font=small_font, fill=(91, 130, 145))
    draw.text((12, top + step * 5 + 2, 48, top + step * 5 + 14), "FRI", font=small_font, fill=(91, 130, 145))

    # Draw the cells and animate a scanning glow
    scan_position = (frame_index / frame_count) * (len(weeks) * step)

    for item in grid:
        x = item["x"]
        y = item["y"]
        color = colors.get(item["level"], colors["NONE"])

        distance = abs((x - left) - scan_position)
        distance = min(distance, len(weeks) * step - distance)

        if distance < 55:
            boost = int((1 - distance / 55) * 85)
            color = tuple(min(255, channel + boost) for channel in color)

        draw.rounded_rectangle(
            (x, y, x + cell, y + cell),
            radius=3,
            fill=color
        )

    # Footer legend
    legend_y = top + step * 7 + 8
    draw.text((left, legend_y), "LESS", font=small_font, fill=(91, 130, 145))

    for index, level in enumerate(
        ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]
    ):
        x = left + 37 + index * 19
        draw.rounded_rectangle(
            (x, legend_y, x + 12, legend_y + 12),
            radius=3,
            fill=colors[level]
        )

    draw.text(
        (left + 145, legend_y),
        "MORE",
        font=small_font,
        fill=(91, 130, 145)
    )

    # Small animated indicator
    indicator_x = width - 35
    indicator_y = 30
    glow = 145 + int(70 * (1 + __import__("math").sin(frame_index * 0.7)) / 2)

    draw.ellipse(
        (indicator_x, indicator_y, indicator_x + 9, indicator_y + 9),
        fill=(0, glow, min(255, glow + 35))
    )

    frames.append(base)

os.makedirs("dist", exist_ok=True)

frames[0].save(
    OUTPUT,
    save_all=True,
    append_images=frames[1:],
    duration=130,
    loop=0,
    optimize=True,
    disposal=2
)

print(f"Generated {OUTPUT}")
print(f"Total contributions: {total}")
print(f"Weeks displayed: {len(weeks)}")