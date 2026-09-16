"""
Щоденний дайджест новин email-маркетингу в Telegram-канал.
"""

import os
import json
import time
import hashlib
import datetime
import urllib.parse

import feedparser
import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

KEYWORDS = [
    "email marketing",
    "email deliverability",
    "email marketing automation",
]

MAX_ITEMS = 8
SEEN_MAX_AGE_DAYS = 14
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")


def build_feed_url(keyword: str) -> str:
    query = f"{keyword} when:1d"
    params = {"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


def entry_timestamp(entry) -> float:
    parsed = entry.get("published_parsed")
    return time.mktime(parsed) if parsed else 0.0


def fetch_items():
    items = []
    seen_links = set()
    for keyword in KEYWORDS:
        feed = feedparser.parse(build_feed_url(keyword))
        for entry in feed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "").strip()
            if not link or not title or link in seen_links:
                continue
            seen_links.add(link)
            items.append({"title": title, "link": link, "ts": entry_timestamp(entry)})
    items.sort(key=lambda x: x["ts"], reverse=True)
    return items


def link_hash(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:16]


def load_seen() -> dict:
    if not os.path.exists(SEEN_FILE):
        return {}
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_seen(seen: dict) -> None:
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)


def cleanup_seen(seen: dict) -> dict:
    cutoff = time.time() - SEEN_MAX_AGE_DAYS * 86400
    return {h: ts for h, ts in seen.items() if ts > cutoff}


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }, timeout=30)
    resp.raise_for_status()


def main():
    seen = cleanup_seen(load_seen())
    items = fetch_items()

    fresh = []
    for item in items:
        h = link_hash(item["link"])
        if h in seen:
            continue
        fresh.append(item)
        seen[h] = time.time()
        if len(fresh) >= MAX_ITEMS:
            break

    save_seen(seen)

    if not fresh:
        print("Немає нових новин за сьогодні — пост не публікуємо.")
        return

    today = datetime.date.today().strftime("%d.%m.%Y")
    lines = [f"📬 <b>Email marketing — дайджест за {today}</b>", ""]
    for item in fresh:
        lines.append(f'• <a href="{item["link"]}">{escape_html(item["title"])}</a>')
    text = "\n".join(lines)

    send_telegram_message(text)
    print(f"Опубліковано {len(fresh)} новин.")


if __name__ == "__main__":
    main()
