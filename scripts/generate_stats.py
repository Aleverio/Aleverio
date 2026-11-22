#!/usr/bin/env python3
"""Generate live GitHub stats SVG cards for the profile README.

Fetches real data from the GitHub API and renders themed SVG cards.
Run locally or via GitHub Actions (every 6h). No third-party services.
"""
import glob
import json
import os
import sys
import textwrap
import urllib.request
from datetime import datetime, timedelta, timezone
from math import gcd

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


def graphql(query, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": "Bearer " + token,
                 "User-Agent": "alkeyy-profile-stats",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def public_events():
    events = []
    for page in (1, 2, 3):
        try:
            batch = get(f"/users/{USER}/events/public?per_page=100&page={page}")
        except Exception:
            break
        if not batch:
            break
        events.extend(batch)
    return events


def event_stats(events):
    days, by_repo = {}, {}
    commits = prs = creates = 0
    push_repos, push_days = set(), {}
    for e in events:
        day = e["created_at"][:10]
        t = e["type"]
        n = 0
        if t == "PushEvent":
            repo = e["repo"]["name"]
            push_repos.add(repo)
            n = e["payload"].get("size") or len(e["payload"].get("commits", [])) or 1
            push_days.setdefault(repo, {})
            push_days[repo][day] = push_days[repo].get(day, 0) + n
        elif t == "PullRequestEvent" and e["payload"].get("action") == "opened":
            prs += 1
            n = 1
        elif t == "CreateEvent":
            creates += 1
            n = 1
        elif t in ("IssuesEvent", "IssueCommentEvent", "PullRequestReviewEvent"):
            n = 1
        if n:
            days[day] = days.get(day, 0) + n
    since = (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo in list(push_repos)[:6]:
        try:
            cl = get(f"/repos/{repo}/commits?author={USER}&since={since}&per_page=100")
        except Exception:
            cl = None
        if cl is None:
            n = sum(push_days[repo].values())
            by_repo[repo] = n
            commits += n
            continue
        by_repo[repo] = len(cl)
        commits += len(cl)
        for d, n in push_days[repo].items():
            days[d] = days.get(d, 0) - n
        for c in cl:
            d = (c["commit"].get("author") or {}).get("date", "")[:10]
            if d:
                days[d] = days.get(d, 0) + 1
    days = {d: n for d, n in days.items() if n > 0}
    return days, by_repo, commits, prs, creates


HEAT = ["#161B22", "#4A2113", "#7A3416", "#B7410E", "#F74C00", "#FFB454"]


def graphql_activity(token):
    now = datetime.now(timezone.utc)
    frm = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    q = ('{user(login:"%s"){contributionsCollection(from:"%s",to:"%s"){'
         'totalCommitContributions pullRequestContributions{totalCount} '
         'repositoryContributions{totalCount} '
         'commitContributionsByRepository(maxRepositories:30){'
         'repository{nameWithOwner isPrivate} contributions{totalCount}}}}}') % (USER, frm, to)
    cc = graphql(q, token)["data"]["user"]["contributionsCollection"]
    by_repo, public = {}, 0
    for c in cc["commitContributionsByRepository"]:
        n = c["contributions"]["totalCount"]
        if c["repository"]["isPrivate"]:
            continue  # never leak private repo names — aggregate only
        by_repo[c["repository"]["nameWithOwner"]] = n
        public += n
    private = max(0, cc["totalCommitContributions"] - public)
    return by_repo, public, cc["pullRequestContributions"]["totalCount"], cc["repositoryContributions"]["totalCount"], private


def heat_level(n):
    if n <= 0:
        return 0
    if n == 1:
        return 1
    if n <= 3:
        return 2
    if n <= 6:
        return 3
    if n <= 9:
        return 4
    return 5


def heatmap_card(days_fallback, total_fallback):
    token = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    weeks = None
    total = None
    if token:
        try:
            q = ('{user(login:"%s"){contributionsCollection{contributionCalendar'
                 '{totalContributions weeks{contributionDays{date contributionCount}}}}}}') % USER
            cal = graphql(q, token)["data"]["user"]["contributionsCollection"]["contributionCalendar"]
            weeks = [[(d["date"], d["contributionCount"]) for d in w["contributionDays"]] for w in cal["weeks"]]
            total = cal["totalContributions"]
        except Exception:
            weeks = None
    if weeks is None:
        today = datetime.now(timezone.utc).date()
        sunday = today - timedelta(days=(today.weekday() + 1) % 7)
        start = sunday - timedelta(weeks=12)
        weeks = []
        for w in range(13):
            week = []
            for d in range(7):
                date = start + timedelta(weeks=w, days=d)
                week.append((date.isoformat(), days_fallback.get(date.isoformat(), 0) if date <= today else -1))
            weeks.append(week)
        total = total_fallback
    nw = len(weeks)
    cell, gap = 12, 3
    gw = nw * (cell + gap) - gap
    x0 = 34
    y0 = 64
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="204" viewBox="0 0 840 204" font-family="\'Segoe UI\',Ubuntu,Sans-Serif">'
        "<style>"
        ".ht{font-size:15px;font-weight:700;fill:#F74C00}"
        ".hm{font-size:10px;fill:#7D8590}"
        ".hn{font-size:10px;fill:#7D8590}"
        ".hb{font-size:22px;font-weight:700;fill:#FFB454;font-family:'JetBrains Mono',Consolas,monospace}"
        "</style>"
        '<rect x="0.5" y="0.5" width="839" height="203" rx="10" fill="#0D1117" stroke="#30363D"/>'
        '<rect x="1" y="1" width="838" height="3" rx="1.5" fill="#F74C00" opacity="0.85"/>'
    )
    label = (f"{total} contributions in the last year" if nw > 30
             else f"{total} public contributions · last 90 days")
    body += f'<text x="25" y="36" class="ht">{esc(label)}</text>'
    last_month = ""
    for wi, week in enumerate(weeks):
        x = x0 + wi * (cell + gap)
        if week:
            m = datetime.fromisoformat(week[0][0]).strftime("%b")
            if m != last_month:
                body += f'<text x="{x}" y="{y0 - 8}" class="hm">{m}</text>'
                last_month = m
        for di, (date, n) in enumerate(week):
            if n < 0:
                continue
            y = y0 + di * (cell + gap)
            body += (f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="2.5" fill="{HEAT[heat_level(n)]}">'
                     f'<title>{date}: {n}</title></rect>')
    for di, lbl in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        body += f'<text x="8" y="{y0 + di * (cell + gap) + 10}" class="hm">{lbl}</text>'
    if nw <= 30:
        # fallback mode: grid is narrow — fill the right side with a live stats panel
        active = sum(1 for n in days_fallback.values() if n > 0)
        best = max(days_fallback.items(), key=lambda kv: kv[1]) if days_fallback else None
        streak, d = 0, datetime.now(timezone.utc).date()
        if days_fallback.get(d.isoformat(), 0) <= 0:
            d -= timedelta(days=1)
        while days_fallback.get(d.isoformat(), 0) > 0:
            streak += 1
            d -= timedelta(days=1)
        best_lbl = (datetime.fromisoformat(best[0]).strftime("%b %d") + f" · {best[1]}") if best else "—"
        body += '<line x1="270" y1="60" x2="270" y2="178" stroke="#21262D"/>'
        panels = [(310, 96, str(total), "public contributions"),
                  (580, 96, str(active), "active days"),
                  (310, 156, best_lbl, "best day"),
                  (580, 156, str(streak), "day streak right now")]
        for px, py, val, lbl in panels:
            body += (f'<text x="{px}" y="{py}" class="hb">{esc(val)}</text>'
                     f'<text x="{px}" y="{py + 18}" class="hn">{esc(lbl)}</text>')
    lx = 840 - 25 - 6 * 15 - 60
    body += f'<text x="{lx}" y="196" class="hn">Less</text>'
    for i in range(6):
        body += f'<rect x="{lx + 30 + i * 15}" y="187" width="11" height="11" rx="2.5" fill="{HEAT[i]}"/>'
    body += f'<text x="{lx + 30 + 6 * 15 + 4}" y="196" class="hn">More</text>'
    body += "</svg>"
    return body


def activity_card(by_repo, commits, prs, creates, repos, private=0):
    top = sorted(((k, v) for k, v in by_repo.items() if v > 0), key=lambda kv: -kv[1])[:3]
    recent_repos = [r["name"] for r in repos
                    if not r["fork"] and r["created_at"] >= (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()]
    creates = max(creates, len(recent_repos))
    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="196" viewBox="0 0 840 196" font-family="\'Segoe UI\',Ubuntu,Sans-Serif">'
        "<style>"
        ".at{font-size:15px;font-weight:700;fill:#F74C00}"
        ".as{font-size:13px;font-weight:600;fill:#E6EDF3}"
        ".ar{font-size:12px;fill:#E6EDF3;font-family:'JetBrains Mono',Consolas,monospace}"
        ".ac{font-size:11px;fill:#7D8590}"
        ".ab{font-size:26px;font-weight:700;fill:#FFB454;font-family:'JetBrains Mono',Consolas,monospace}"
        ".al{font-size:11px;fill:#7D8590}"
        ".fade{animation:fade .8s ease both}"
        "@keyframes fade{from{opacity:0}to{opacity:1}}"
        "</style>"
        '<rect x="0.5" y="0.5" width="839" height="195" rx="10" fill="#0D1117" stroke="#30363D"/>'
        '<rect x="1" y="1" width="838" height="3" rx="1.5" fill="#F74C00" opacity="0.85"/>'
        '<text x="25" y="36" class="at">Contribution Activity</text>'
        '<text x="200" y="36" class="ac">last 90 days · public events</text>'
    )
    nrepos = len(by_repo)
    summary = f'Created {commits} commits in {nrepos} repositor{"y" if nrepos == 1 else "ies"}'
    if private:
        summary += f'  ·  +{private} in private repos (anonymized)'
    body += f'<text x="25" y="68" class="as">{esc(summary)}</text>'
    if top:
        mx = max(top[0][1], 1)
        for i, (repo, n) in enumerate(top):
            y = 96 + i * 30
            bw = max(6, int(240 * n / mx))
            short = repo.split("/")[-1]
            body += (
                f'<g class="fade" style="animation-delay:{i * 120}ms">'
                f'<text x="25" y="{y}" class="ar">{esc(short)}</text>'
                f'<rect x="220" y="{y - 9}" width="{bw}" height="9" rx="4.5" fill="#F74C00"/>'
                f'<rect x="220" y="{y - 9}" width="{bw}" height="9" rx="4.5" fill="#FFB454" opacity="0.25"/>'
                f'<text x="{220 + bw + 10}" y="{y}" class="ac">{n} commit{"s" if n != 1 else ""}</text></g>'
            )
    else:
        body += '<text x="25" y="100" class="ac">warming up — commits incoming…</text>'
    body += '<line x1="560" y1="58" x2="560" y2="180" stroke="#21262D"/>'
    body += (f'<text x="600" y="100" class="ab">{creates}</text>'
             '<text x="600" y="118" class="al">repositories created</text>'
             f'<text x="720" y="100" class="ab">{prs}</text>'
             '<text x="720" y="118" class="al">pull requests opened</text>')
    body += "</svg>"
    return body


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def card_open(w, h, title):
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" font-family="'Segoe UI',Ubuntu,Sans-Serif">
<style>
.title{{font-size:16px;font-weight:700;fill:#F74C00}}
.label{{font-size:13px;fill:#E6EDF3}}
.value{{font-size:13px;font-weight:700;fill:#FFB454;font-family:'JetBrains Mono',Consolas,monospace}}
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
    return (
        card_open(420, 216, f"{esc(user['name'] or USER)}'s GitHub Stats")
        + body
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
        card_open(420, 216, "Most Used Languages")
        + bar
        + legend
        + "</svg>"
    )


QUOTE_INTERVAL = 600  # seconds — one fresh quote every 10 minutes

QUOTES = [
    # --- original 16 -----------------------------------------------------
    ("The impediment to action advances action. What stands in the way becomes the way.", "Marcus Aurelius"),
    ("We suffer more often in imagination than in reality.", "Seneca"),
    ("Fall seven times, stand up eight.", "Japanese Proverb"),
    ("The best time to plant a tree was 20 years ago. The second best time is now.", "Chinese Proverb"),
    ("It always seems impossible until it's done.", "Nelson Mandela"),
    ("You do not rise to the level of your goals. You fall to the level of your systems.", "James Clear"),
    ("A ship in harbor is safe, but that is not what ships are built for.", "John A. Shedd"),
    ("He who has a why to live can bear almost any how.", "Friedrich Nietzsche"),
    ("The cave you fear to enter holds the treasure you seek.", "Joseph Campbell"),
    ("Knowing is not enough; we must apply. Willing is not enough; we must do.", "Bruce Lee"),
    ("Everything you've ever wanted is on the other side of fear.", "George Addair"),
    ("The man who moves a mountain begins by carrying away small stones.", "Confucius"),
    ("Your future is created by what you do today, not tomorrow.", "Robert Kiyosaki"),
    ("Hard choices, easy life. Easy choices, hard life.", "Jerzy Gregorek"),
    ("Small daily improvements are the key to staggering long-term results.", "Robin Sharma"),
    ("Discipline equals freedom.", "Jocko Willink"),
    # --- 45 more: people who actually lived it ---------------------------
    ("The only way to do great work is to love what you do.", "Steve Jobs"),
    ("Your time is limited, so don't waste it living someone else's life.", "Steve Jobs"),
    ("You can't connect the dots looking forward; you can only connect them looking backwards.", "Steve Jobs"),
    ("Stay hungry, stay foolish.", "Steve Jobs"),
    ("Life is what happens when you're busy making other plans.", "John Lennon"),
    ("An unexamined life is not worth living.", "Socrates"),
    ("The only true wisdom is in knowing you know nothing.", "Socrates"),
    ("The best way to find yourself is to lose yourself in the service of others.", "Mahatma Gandhi"),
    ("I have not failed. I've just found 10,000 ways that won't work.", "Thomas Edison"),
    ("Genius is one percent inspiration and ninety-nine percent perspiration.", "Thomas Edison"),
    ("The future belongs to those who believe in the beauty of their dreams.", "Eleanor Roosevelt"),
    ("No one can make you feel inferior without your consent.", "Eleanor Roosevelt"),
    ("Try not to become a man of success, but rather try to become a man of value.", "Albert Einstein"),
    ("Life is like riding a bicycle. To keep your balance, you must keep moving.", "Albert Einstein"),
    ("Anyone who has never made a mistake has never tried anything new.", "Albert Einstein"),
    ("In the middle of difficulty lies opportunity.", "Albert Einstein"),
    ("If I have seen further, it is by standing on the shoulders of giants.", "Isaac Newton"),
    ("The best way to predict the future is to invent it.", "Alan Kay"),
    ("Simple things should be simple, complex things should be possible.", "Alan Kay"),
    ("Success is a lousy teacher. It seduces smart people into thinking they can't lose.", "Bill Gates"),
    ("Perfection is attained not when there is nothing more to add, but when there is nothing more to remove.", "Antoine de Saint-Exupéry"),
    ("The details are not the details. They make the design.", "Charles Eames"),
    ("Premature optimization is the root of all evil.", "Donald Knuth"),
    ("Programs must be written for people to read, and only incidentally for machines to execute.", "Harold Abelson"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    ("I've failed over and over and over again in my life. And that is why I succeed.", "Michael Jordan"),
    ("Talent wins games, but teamwork and intelligence win championships.", "Michael Jordan"),
    ("You miss 100% of the shots you don't take.", "Wayne Gretzky"),
    ("A good plan violently executed now is better than a perfect plan executed next week.", "George S. Patton"),
    ("Plans are worthless, but planning is everything.", "Dwight D. Eisenhower"),
    ("Do the best you can until you know better. Then when you know better, do better.", "Maya Angelou"),
    ("The time is always right to do what is right.", "Martin Luther King Jr."),
    ("Darkness cannot drive out darkness; only light can do that. Hate cannot drive out hate; only love can do that.", "Martin Luther King Jr."),
    ("If you want to go quickly, go alone. If you want to go far, go together.", "African Proverb"),
    ("A journey of a thousand miles begins with a single step.", "Lao Tzu"),
    ("Nature does not hurry, yet everything is accomplished.", "Lao Tzu"),
    ("The quieter you become, the more you are able to hear.", "Rumi"),
    ("The wound is the place where the Light enters you.", "Rumi"),
    ("Yesterday I was clever, so I wanted to change the world. Today I am wise, so I am changing myself.", "Rumi"),
    ("Inspiration exists, but it has to find you working.", "Pablo Picasso"),
    ("How we spend our days is, of course, how we spend our lives.", "Annie Dillard"),
    ("Tell me, what is it you plan to do with your one wild and precious life?", "Mary Oliver"),
    ("In three words I can sum up everything I've learned about life: it goes on.", "Robert Frost"),
    ("Not all those who wander are lost.", "J.R.R. Tolkien"),
    ("The secret of getting ahead is getting started.", "Mark Twain"),
]


def quote_card():
    """Render a self-contained SVG that rotates every quote every 10 minutes.

    The rotation lives *inside* the SVG as CSS animations, so it keeps ticking
    in the viewer's browser even if GitHub Actions is late or the raw image is
    cached. Negative animation delays are seeded from the current UTC clock so
    every visitor lands on the same wall-clock quote.
    """
    n = len(QUOTES)
    period = n * QUOTE_INTERVAL
    now_s = int(datetime.now(timezone.utc).timestamp())
    delay = now_s % period
    step = 100.0 / n
    # Coprime stride => every quote gets its turn before the cycle repeats.
    stride = n // 2
    while gcd(stride, n) != 1:
        stride -= 1

    css = [
        ".qtext{font-size:18px;font-style:italic;fill:#E6EDF3}",
        ".author{font-size:14px;font-weight:700;fill:#FFB454}",
    ]
    groups = []
    for slot in range(n):
        text, author = QUOTES[(slot * stride) % n]
        wrapped = textwrap.wrap(text, width=72)
        lines = wrapped[:3]
        if len(wrapped) > 3:
            lines[2] = lines[2][:69].rstrip() + "..."
        y0 = 62 if len(lines) == 1 else (52 if len(lines) == 2 else 42)
        s, e = slot * step, (slot + 1) * step
        css.append(f".q{slot}{{opacity:0;animation:q{slot} {period}s linear -{delay}s infinite}}")
        css.append(
            f"@keyframes q{slot}{{0%{{opacity:0}}"
            f"{s:.4f}%{{opacity:0}}"
            f"{s + 0.004:.4f}%{{opacity:1}}"
            f"{e - 0.004:.4f}%{{opacity:1}}"
            f"{e:.4f}%{{opacity:0}}"
            f"100%{{opacity:0}}}}"
        )
        g = f'<g class="q{slot}">'
        for i, line in enumerate(lines):
            g += f'<text x="95" y="{y0 + i * 26}" class="qtext">{esc(line)}</text>'
        g += f'<text x="810" y="{y0 + len(lines) * 26 + 14}" text-anchor="end" class="author">— {esc(author)}</text></g>'
        groups.append(g)

    body = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="150" viewBox="0 0 840 150" font-family="\'Segoe UI\',Ubuntu,Sans-Serif">'
        "<style>" + "\n".join(css) + "</style>"
        '<rect x="0.5" y="0.5" width="839" height="149" rx="10" fill="#0D1117" stroke="#30363D"/>'
        '<rect x="1" y="12" width="3" height="126" rx="1.5" fill="#F74C00" opacity="0.9"/>'
        '<text x="30" y="82" font-size="72" font-weight="700" fill="#F74C00" opacity="0.85" font-family="Georgia,serif">&#8220;</text>'
        + "".join(groups)
        + "</svg>"
    )
    return body


ICON_REPO = "M2 2.5A2.5 2.5 0 0 1 4.5 0h8.75a.75.75 0 0 1 .75.75v12.5a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h1.75v-2h-8a1 1 0 0 0-.714 1.7.75.75 0 1 1-1.072 1.05A2.495 2.495 0 0 1 2 11.5Zm10.5-1h-8a1 1 0 0 0-1 1v6.708A2.486 2.486 0 0 1 4.5 9h8ZM5 12.25a.25.25 0 0 1 .25-.25h3.5a.25.25 0 0 1 .25.25v3.25a.25.25 0 0 1-.4.2l-1.45-1.087a.249.249 0 0 0-.3 0L5.4 15.7a.25.25 0 0 1-.4-.2Z"
ICON_STAR = "M8 .25a.75.75 0 0 1 .673.418l1.882 3.815 4.21.612a.75.75 0 0 1 .416 1.279l-3.046 2.97.719 4.192a.751.751 0 0 1-1.088.791L8 12.347l-3.766 1.98a.75.75 0 0 1-1.088-.79l.72-4.194L.818 6.374a.75.75 0 0 1 .416-1.28l4.21-.611L7.327.668A.75.75 0 0 1 8 .25Z"
ICON_FORK = "M5 5.372v.878c0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75v-.878a2.25 2.25 0 1 1 1.5 0v.878a2.25 2.25 0 0 1-2.25 2.25h-1.5v2.128a2.251 2.251 0 1 1-1.5 0V8.5h-1.5A2.25 2.25 0 0 1 3.5 6.25v-.878a2.25 2.25 0 1 1 1.5 0ZM5 3.25a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Zm6.75.75a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm-3 8.75a.75.75 0 1 0-1.5 0 .75.75 0 0 0 1.5 0Z"


def octicon(path, x, y, fill, scale=0.85):
    return f'<path transform="translate({x},{y}) scale({scale})" fill="{fill}" d="{path}"/>'


def ago(iso):
    then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    days = (datetime.now(timezone.utc) - then).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


def repo_card(r, delay):
    name = r["name"]
    desc = r["description"] or "No description yet — cooking something good…"
    wrapped = textwrap.wrap(desc, width=60)[:2]
    if len(textwrap.wrap(desc, width=60)) > 2:
        wrapped[1] = wrapped[1][:57].rstrip() + "…"
    lang = r["language"]
    lcolor = LANG_COLORS.get(lang, "#7D8590")
    body = (
        f'<g class="fade" style="animation-delay:{delay}ms">'
        '<rect x="0.5" y="0.5" width="419" height="149" rx="10" fill="#0D1117" stroke="#30363D"/>'
        '<rect x="1" y="12" width="3" height="126" rx="1.5" fill="#F74C00" opacity="0.9"/>'
        + octicon(ICON_REPO, 22, 19, "#F74C00")
        + f'<text x="44" y="32" class="rname">{esc(name)}</text>'
    )
    if r["fork"]:
        body += (
            '<rect x="352" y="16" width="52" height="20" rx="10" fill="#21262D" stroke="#30363D"/>'
            + octicon(ICON_FORK, 360, 20, "#FFB454", 0.7)
            + '<text x="376" y="30" class="forkpill">fork</text>'
        )
    for i, line in enumerate(wrapped):
        body += f'<text x="22" y="{62 + i * 18}" class="rdesc">{esc(line)}</text>'
    body += '<line x1="22" y1="106" x2="398" y2="106" stroke="#21262D"/>'
    x = 22
    if lang:
        body += f'<circle cx="{x + 5}" cy="125" r="5" fill="{lcolor}"/><text x="{x + 15}" y="129" class="rmeta">{esc(lang)}</text>'
        x += 15 + 7 * len(lang) + 22
    body += octicon(ICON_STAR, x, 118, "#FFB454", 0.8) + f'<text x="{x + 17}" y="129" class="rmeta">{r["stargazers_count"]}</text>'
    x += 17 + 8 * len(str(r["stargazers_count"])) + 20
    body += octicon(ICON_FORK, x, 118, "#7D8590", 0.8) + f'<text x="{x + 17}" y="129" class="rmeta">{r["forks_count"]}</text>'
    body += f'<text x="398" y="129" text-anchor="end" class="rtime">updated {ago(r["pushed_at"] or r["updated_at"])}</text>'
    body += "</g>"
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="150" viewBox="0 0 420 150" font-family="\'Segoe UI\',Ubuntu,Sans-Serif">'
        "<style>"
        ".rname{font-size:15px;font-weight:700;fill:#E6EDF3}"
        ".rdesc{font-size:12px;fill:#7D8590}"
        ".rmeta{font-size:12px;fill:#E6EDF3;font-family:'JetBrains Mono',Consolas,monospace}"
        ".rtime{font-size:11px;fill:#7D8590}"
        ".forkpill{font-size:11px;font-weight:600;fill:#FFB454}"
        ".fade{animation:fade .7s ease both}"
        "@keyframes fade{from{opacity:0}to{opacity:1}}"
        "</style>" + body + "</svg>"
    )


def repos_section(repos):
    rows = [r for r in repos if r["name"] != USER]
    rows.sort(key=lambda r: r["pushed_at"] or r["updated_at"], reverse=True)
    rows.sort(key=lambda r: (r["fork"], -r["stargazers_count"]))
    for old in glob.glob(os.path.join(OUT, "repo-*.svg")):
        os.remove(old)
    cards = []
    for i, r in enumerate(rows):
        fname = f"repo-{r['name']}.svg"
        with open(os.path.join(OUT, fname), "w", encoding="utf-8") as f:
            f.write(repo_card(r, i * 100))
        cards.append(f'<a href="{r["html_url"]}"><img src="./assets/{fname}" width="400" alt="{esc(r["name"])}" /></a>')
    lines = ['<div align="center">', ""]
    for i in range(0, len(cards), 2):
        lines.append(" ".join(cards[i:i + 2]))
        lines.append("")
    lines.append("</div>")
    return "\n".join(lines)


def sync_readme(table):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "README.md")
    with open(path, encoding="utf-8") as f:
        md = f.read()
    start, end = "<!-- REPOS:START -->", "<!-- REPOS:END -->"
    if start in md and end in md:
        pre, rest = md.split(start, 1)
        _, post = rest.split(end, 1)
        md = pre + start + "\n" + table + "\n" + end + post
        with open(path, "w", encoding="utf-8") as f:
            f.write(md)
        print("synced README repo table")


def main():
    if "--quote-only" in sys.argv:
        os.makedirs(OUT, exist_ok=True)
        path = os.path.join(OUT, "quote.svg")
        with open(path, "w", encoding="utf-8") as f:
            f.write(quote_card())
        print("wrote", os.path.normpath(path))
        return
    user = get(f"/users/{USER}")
    repos = get(f"/users/{USER}/repos?per_page=100&type=owner")
    os.makedirs(OUT, exist_ok=True)
    events = public_events()
    days, by_repo, commits, prs, creates = event_stats(events)
    private = 0
    token = os.environ.get("PROFILE_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        try:
            by_repo, commits, prs, creates, private = graphql_activity(token)
        except Exception:
            pass  # fall back to public events
    for name, svg in [("metrics-stats.svg", stats_card(user, repos)),
                      ("metrics-langs.svg", langs_card(repos)),
                      ("quote.svg", quote_card()),
                      ("heatmap.svg", heatmap_card(days, sum(days.values()))),
                      ("activity.svg", activity_card(by_repo, commits, prs, creates, repos, private))]:
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print("wrote", os.path.normpath(path))
    sync_readme(repos_section(repos))


if __name__ == "__main__":
    main()
