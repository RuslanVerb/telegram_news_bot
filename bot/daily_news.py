"""
Щоденний дайджест новин email-маркетингу в Telegram-канал.

Джерело новин — RSS-пошук Google News (без платних API).
Показуються лише новини з довіреного списку джерел (ALLOWED_DOMAINS) —
щоб у дайджест не потрапляли випадкові агрегатори чи нерелевантні сайти.
Стан "вже опублікованого" зберігається у seen.json поруч зі скриптом.

Потрібні змінні середовища:
  TELEGRAM_BOT_TOKEN — токен бота від @BotFather
  TELEGRAM_CHAT_ID   — @username каналу (якщо публічний) або числовий chat_id
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

# Ключові запити — можна редагувати під потрібні теми.
# "site:validity.com" — окремий запит, що бере тільки свіжі публікації
# з блогу Validity (у них немає окремого публічного RSS з передбачуваною
# адресою, тому це найнадійніший спосіб отримувати саме їхній контент).
KEYWORDS = [
    "email marketing",
    "email deliverability",
    "email marketing automation",
    "site:validity.com",
]

# Довірені джерела — новина публікується, лише якщо Google News
# позначив її оригінальне джерело одним з цих доменів.
# Список легко розширювати чи скорочувати під себе.
ALLOWED_DOMAINS = {
    "litmus.com",
    "validity.com",
    "emailonacid.com",
    "reallygoodemails.com",
    "klaviyo.com",
    "mailchimp.com",
    "sparkpost.com",
    "activecampaign.com",
    "campaignmonitor.com",
    "omnisend.com",
    "marketingprofs.com",
    "searchenginejournal.com",
    "smartinsights.com",
    "martech.org",
    "chiefmartec.com",
    "hubspot.com",
    "marketingdive.com",
    "adweek.com",
    "mailjet.com",
    "sendgrid.com",
    "postmark.com",
    "glockapps.com",
}

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


def source_domain(entry) -> str:
    """Домен оригінального видавця з тегу <source url="..."> Google News."""
    source = entry.get("source")
    href = source.get("href", "") if source else ""
    if not href:
        return ""
    netloc = urllib.parse.urlparse(href).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def domain_allowed(domain: str) -> bool:
    if not domain:
        return False
    return any(domain == d or domain.endswith("." + d) for d in ALLOWED_DOMAINS)


def clean_title(title: str, source_name: str) -> str:
    """Прибирає дублювання типу 'Title - Litmus', якщо джерело вже відоме."""
    if not source_name:
        return title
    suffix = f" - {source_name}"
    if title.lower().endswith(suffix.lower()):
        return title[: -len(suffix)].strip()
    return title


def fetch_items():
    items = []
    seen_links = set()
    for keyword in KEYWORDS:
        feed = feedparser.parse(build_feed_url(keyword))
        for entry in feed.entries:
            link = entry.get("link", "")
            raw_title = entry.get("title", "").strip()
            if not link or not raw_title or link in seen_links:
                continue

            domain = source_domain(entry)
            if not domain_allowed(domain):
                continue

            source = entry.get("source") or {}
            source_name = source.get("title", "") if source else ""

            seen_links.add(link)
            items.append({
                "title": clean_title(raw_title, source_name),
                "source": source_name,
                "link": link,
                "ts": entry_timestamp(entry),
            })
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
    if resp.status_code != 200:
        print("Telegram відповів помилкою:", resp.text)
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
        print("Немає нових новин з довірених джерел за сьогодні — пост не публікуємо.")
        return

    today = datetime.date.today().strftime("%d.%m.%Y")
    lines = [f"📬 <b>Email marketing — дайджест за {today}</b>", ""]
    for item in fresh:
        title = escape_html(item["title"])
        line = f'• <a href="{item["link"]}">{title}</a>'
        if item["source"]:
            line += f' — {escape_html(item["source"])}'
        lines.append(line)
    text = "\n".join(lines)

    send_telegram_message(text)
    print(f"Опубліковано {len(fresh)} новин.")


if __name__ == "__main__":
    main()
