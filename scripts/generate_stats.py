#!/usr/bin/env python3
"""Generate live GitHub stats SVG cards for the profile README.

Fetches real data from the GitHub API and renders themed SVG cards.
Run locally or via GitHub Actions (every 6h). No third-party services.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

USER = "Aleverio"
API = "https://api.github.com"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets")

LANG_COLORS = {
    "Rust": "#DEA584", "TypeScript": "#3178C6", "JavaScript": "#F1E05A",
    "Python": "#3572A5", "C++": "#F34B7D", "C": "#555555", "HTML": "#E34C26",
    "CSS": "#663399", "Lua": "#000080", "Shell": "#89E051", "Clojure": "#DB5855",
    "Go": "#00ADD8", "Java": "#B07219", "C#": "#178600", "PHP": "#4F5D95",
}
FALLBACK = ["#F74C00", "#FFB454", "#B7410E", "#38BDF8", "#238636"]


def get(path):
    req = urllib.request.Request(API + path, headers={
        "User-Agent": "alkeyy-profile-stats",
        "Accept": "application/vnd.github+json",
    })
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", "Bearer " + token)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def live_dot(x):
    return (
        f'<circle cx="{x}" cy="31" r="4" fill="#3FB950">'
        '<animate attributeName="opacity" values="1;0.25;1" dur="2s" repeatCount="indefinite"/>'
        "</circle>"
        f'<text x="{x + 10}" y="35" class="live">LIVE</text>'
    )


def card_open(w, h, title):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="'Segoe UI',Ubuntu,Sans-Serif">
<style>
.title{{font-size:16px;font-weight:700;fill:#F74C00}}
.label{{font-size:13px;fill:#E6EDF3}}
.value{{font-size:13px;font-weight:700;fill:#FFB454;font-family:'JetBrains Mono',Consolas,monospace}}
.note{{font-size:10px;fill:#7D8590}}
.live{{font-size:10px;font-weight:700;fill:#3FB950;letter-spacing:1px}}
.pct{{font-size:12px;fill:#7D8590;font-family:'JetBrains Mono',Consolas,monospace}}
.fade{{animation:fade .8s ease both}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
</style>
<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="10" fill="#0D1117" stroke="#30363D"/>
<rect x="1" y="1" width="{w - 2}" height="3" rx="1.5" fill="#F74C00" opacity="0.85"/>
<text x="25" y="36" class="title">{esc(title)}</text>
'''


def stats_card(user, repos):
    own = [r for r in repos if not r["fork"]]
    stars = sum(r["stargazers_count"] for r in repos)
    forks = sum(r["forks_count"] for r in repos)
    since = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00")).year
    rows = [
        ("Public Repositories", user["public_repos"]),
        ("Total Stars Earned", stars),
        ("Total Forks", forks),
        ("Followers", user["followers"]),
        ("Following", user["following"]),
        ("On GitHub Since", since),
    ]
    body = ""
    for i, (label, val) in enumerate(rows):
        y = 72 + i * 26
        body += (
            f'<g class="fade" style="animation-delay:{i * 90}ms">'
            f'<circle cx="30" cy="{y - 4}" r="2.5" fill="#F74C00"/>'
            f'<text x="42" y="{y}" class="label">{esc(label)}</text>'
            f'<text x="395" y="{y}" text-anchor="end" class="value">{esc(val)}</text></g>'
        )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        card_open(420, 248, f"{esc(user['name'] or USER)}'s GitHub Stats")
        + live_dot(352)
        + body
        + f'<text x="25" y="232" class="note">auto-refreshed every 6h via GitHub Actions · {stamp}</text>'
        + "</svg>"
    )


def langs_card(repos):
    sizes = {}
    for r in repos:
        if r["fork"]:
            continue
        try:
            langs = get(f"/repos/{USER}/{r['name']}/languages")
        except Exception:
            langs = {r["language"]: max(r["size"], 1) * 1024} if r["language"] else {}
        for name, nbytes in langs.items():
            sizes[name] = sizes.get(name, 0) + nbytes
    total = sum(sizes.values()) or 1
    langs = sorted(sizes.items(), key=lambda kv: -kv[1])[:8]
    color = {}
    fi = 0
    for name, _ in langs:
        if name in LANG_COLORS:
            color[name] = LANG_COLORS[name]
        else:
            color[name] = FALLBACK[fi % len(FALLBACK)]
            fi += 1
    bar = '<clipPath id="bar"><rect x="25" y="58" width="370" height="10" rx="5"/></clipPath><g clip-path="url(#bar)">'
    x = 25.0
    for name, size in langs:
        w = 370 * size / total
        bar += f'<rect x="{x:.2f}" y="58" width="{w + 0.5:.2f}" height="10" fill="{color[name]}"><animate attributeName="opacity" from="0" to="1" dur="0.9s" fill="freeze"/></rect>'
        x += w
    bar += "</g>"
    legend = ""
    for i, (name, size) in enumerate(langs):
        col, row = i % 2, i // 2
        lx, ly = 25 + col * 195, 100 + row * 28
        pct = 100 * size / total
        legend += (
            f'<g class="fade" style="animation-delay:{i * 80}ms">'
            f'<circle cx="{lx + 5}" cy="{ly - 4}" r="5" fill="{color[name]}"/>'
            f'<text x="{lx + 16}" y="{ly}" class="label">{esc(name)}</text>'
            f'<text x="{lx + 170}" y="{ly}" text-anchor="end" class="pct">{pct:.1f}%</text></g>'
        )
    return (
        card_open(420, 248, "Most Used Languages")
        + live_dot(352)
        + bar
        + legend
        + '<text x="25" y="232" class="note">weighted by code bytes · own repos only · refreshed every 6h</text>'
        + "</svg>"
    )


def main():
    user = get(f"/users/{USER}")
    repos = get(f"/users/{USER}/repos?per_page=100&type=owner")
    os.makedirs(OUT, exist_ok=True)
    for name, svg in [("metrics-stats.svg", stats_card(user, repos)),
                      ("metrics-langs.svg", langs_card(repos))]:
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", os.path.normpath(path))


if __name__ == "__main__":
    main()
