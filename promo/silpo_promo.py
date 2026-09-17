"""
Сповіщення про акційні товари «Сільпо» в Telegram.

Бере дані з публічного каталогу silpo.ua (той самий запит, що робить сайт),
фільтрує за списком стеження + мінімальною знижкою і пише тільки про те,
чого ще не було в попередніх запусках.

Потрібні змінні середовища:
  TELEGRAM_BOT_TOKEN — токен бота від @BotFather
  TELEGRAM_CHAT_ID   — @username каналу або числовий chat_id
"""

import os
import json
import time
import datetime

import requests

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# --- НАЛАШТУВАННЯ ---------------------------------------------------------

# Слова, які шукаємо в назві товару (нижній регістр, часткове співпадіння).
# Порожній список = стежити за всім, що перевищує поріг знижки.
WATCHLIST = [
    "кава",
    "сир",
    "оливкова олія",
    "лосось",
    "сьомга",
]

# Мінімальна знижка у відсотках, щоб товар взагалі вважався цікавим.
MIN_DISCOUNT = 20

# Скільки товарів максимум в одному повідомленні.
MAX_ITEMS = 15

# Скільки сторінок каталогу переглядати (100 товарів на сторінку).
# 12000+ акційних позицій загалом; 10 сторінок = 1000 найпопулярніших.
PAGES = 10
PAGE_SIZE = 100

BRANCH_ID = "00000000-0000-0000-0000-000000000000"
API_URL = f"https://sf-ecom-api.silpo.ua/v1/uk/branches/{BRANCH_ID}/products"

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_promo.json")
SEEN_MAX_AGE_DAYS = 21

HEADERS = {
    "accept": "application/json",
    "origin": "https://silpo.ua",
    "referer": "https://silpo.ua/",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
    ),
}

# --- ЛОГІКА ---------------------------------------------------------------


def fetch_page(offset: int) -> list:
    params = {
        "limit": PAGE_SIZE,
        "offset": offset,
        "deliveryType": "DeliveryHome",
        "includeChildCategories": "true",
        "sortBy": "popularity",
        "sortDirection": "desc",
        "mustHavePromotion": "true",
    }
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json().get("items", [])


def fetch_all() -> list:
    items = []
    for page in range(PAGES):
        batch = fetch_page(page * PAGE_SIZE)
        if not batch:
            break
        items.extend(batch)
        time.sleep(0.5)  # не довбимо API
    return items


def discount_percent(item: dict):
    """Відсоток знижки або None, якщо старої ціни немає."""
    old = item.get("displayOldPrice")
    new = item.get("displayPrice")
    if not old or not new or old <= 0 or new >= old:
        return None
    return round((old - new) / old * 100)


def matches_watchlist(title: str) -> bool:
    if not WATCHLIST:
        return True
    low = title.lower()
    return any(word.lower() in low for word in WATCHLIST)


def interesting(item: dict):
    """Повертає dict з даними товару, якщо він нам цікавий, інакше None."""
    title = (item.get("title") or "").strip()
    if not title or not matches_watchlist(title):
        return None

    pct = discount_percent(item)
    if pct is None or pct < MIN_DISCOUNT:
        return None

    slug = item.get("slug") or ""
    return {
        "key": f"{slug}:{item.get('displayPrice')}",
        "title": title,
        "price": item.get("displayPrice"),
        "old_price": item.get("displayOldPrice"),
        "ratio": item.get("displayRatio") or "",
        "percent": pct,
        "url": f"https://silpo.ua/product/{slug}" if slug else "https://silpo.ua/offers",
    }


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
    return {k: ts for k, ts in seen.items() if ts > cutoff}


def escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_message(found: list) -> str:
    today = datetime.date.today().strftime("%d.%m.%Y")
    lines = [f"🛒 <b>Нові акції в «Сільпо» — {today}</b>", ""]
    for it in found:
        ratio = f" / {escape_html(it['ratio'])}" if it["ratio"] else ""
        lines.append(
            f'• <a href="{it["url"]}">{escape_html(it["title"])}</a>\n'
            f'  <b>{it["price"]} грн</b>{ratio} '
            f'<s>{it["old_price"]}</s> −{it["percent"]}%'
        )
    return "\n".join(lines)


def send_telegram_message(text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    if resp.status_code != 200:
        print("Telegram відповів помилкою:", resp.text)
    resp.raise_for_status()


def main():
    seen = cleanup_seen(load_seen())
    items = fetch_all()
    print(f"Отримано {len(items)} акційних позицій з каталогу.")

    found = []
    for item in items:
        info = interesting(item)
        if not info or info["key"] in seen:
            continue
        found.append(info)
        seen[info["key"]] = time.time()
        if len(found) >= MAX_ITEMS:
            break

    save_seen(seen)

    if not found:
        print("Нових цікавих акцій немає — повідомлення не надсилаємо.")
        return

    send_telegram_message(format_message(found))
    print(f"Надіслано {len(found)} товарів.")


if __name__ == "__main__":
    main()
