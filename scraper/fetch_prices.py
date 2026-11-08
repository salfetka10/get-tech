"""Сбор прайса get.tech из открытого канала поставщика.

Читает веб-версию канала поставщика (https://t.me/s/<канал>), находит строки с ценами,
считает цену get.tech и сохраняет data/prices.json. Цены поставщика в файл не попадают.

Запуск: python scraper/fetch_prices.py
Проверка на сохранённом посте: python scraper/fetch_prices.py --text tests/sample_post.txt
"""
import argparse
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Канал поставщика и наценка хранятся в секретах репозитория, чтобы не светиться в открытом коде.
CHANNEL = os.environ.get("SOURCE_CHANNEL", "")
MARKUP = float(os.environ.get("MARKUP") or 0)          # наценка get.tech к цене поставщика, доля (секрет MARKUP)
ROUND_TO = 100                                          # округление вверх, ₽
PACKAGING = int(os.environ.get("PACKAGING", "0"))       # упаковка, ₽ на позицию
POSTS_TO_READ = 30     # сколько последних постов смотреть
MIN_PRICE, MAX_PRICE = 1_000, 1_500_000
MAX_DROP = 0.5         # если позиций стало меньше половины прошлого раза, не обновляем

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"

CATEGORIES = [
    ("iPhone", r"iphone"),
    ("Mac", r"macbook|imac|mac mini|mac studio"),
    ("iPad", r"ipad"),
    ("Наушники", r"airpods|beats|наушник"),
    ("Часы", r"watch"),
]
# цена в конце строки: 118.500 / 118 500 / 118500 / 118 500₽ / 118,5к
PRICE_RE = re.compile(r"(\d{1,3}(?:[ .,  ]\d{3})+|\d{4,7})\s*(?:₽|р\.?|руб\.?)?\s*$", re.I)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


def to_rub(s: str) -> int:
    return int(re.sub(r"\D", "", s))


def our_price(supplier: int) -> int:
    return int(math.ceil((supplier * (1 + MARKUP) + PACKAGING) / ROUND_TO) * ROUND_TO)


def category(text: str) -> str:
    low = text.lower()
    for name, rx in CATEGORIES:
        if re.search(rx, low):
            return name
    return "Другое"


def region(line: str) -> str:
    """Флаг страны → код (US, JP...). Для iPhone это важно: от региона зависят SIM и eSIM."""
    m = FLAG_RE.search(line)
    return "".join(chr(ord(c) - 0x1F1E6 + 65) for c in m.group(0)) if m else ""


def clean(line: str) -> str:
    line = FLAG_RE.sub(" ", line)
    line = EMOJI_RE.sub(" ", line)
    line = re.sub(r"[\-–—:|•·]+\s*$", "", line)
    return re.sub(r"\s+", " ", line).strip(" -–—:|•·")


def parse_post(text: str) -> list[dict]:
    """Строка с ценой = позиция. Строка без цены = заголовок модели для следующих строк."""
    items, header = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            header = ""  # пустая строка закрывает блок модели
            continue
        m = PRICE_RE.search(line)
        if not m:
            h = clean(line)
            if len(h) >= 3 and re.search(r"[a-zа-я]", h, re.I):
                header = h
            continue
        price = to_rub(m.group(1))
        if not MIN_PRICE <= price <= MAX_PRICE:
            continue
        rest = clean(line[: m.start()])
        own_model = category(rest) != "Другое"
        name = rest if own_model or not header or header.lower() in rest.lower() else f"{header} {rest}".strip()
        if not name:
            continue
        items.append({
            "category": category(name),
            "name": name,
            "region": region(line),
            "price": our_price(price),
        })
    return items


def fetch_posts() -> list[dict]:
    import requests
    from bs4 import BeautifulSoup

    url = f"https://t.me/s/{CHANNEL}"
    posts, before = [], None
    while len(posts) < POSTS_TO_READ:
        r = requests.get(url, params={"before": before} if before else None, timeout=30,
                         headers={"User-Agent": "get-tech-price/1.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        found = soup.select(".tgme_widget_message")
        if not found:
            break
        for m in found:
            body = m.select_one(".tgme_widget_message_text")
            when = m.select_one("time[datetime]")
            if body:
                for br in body.find_all("br"):
                    br.replace_with("\n")
                posts.append({"id": m.get("data-post", ""), "time": when["datetime"] if when else None,
                              "text": body.get_text()})
        ids = [int(m.get("data-post", "0").split("/")[-1] or 0) for m in found]
        before = min(ids) if ids else None
        if not before:
            break
    return posts


def build(posts: list[dict]) -> dict:
    # новые посты важнее старых: одна и та же позиция берётся из самого свежего поста
    posts = sorted(posts, key=lambda p: p["time"] or "", reverse=True)
    seen, items = set(), []
    for p in posts:
        for it in parse_post(p["text"]):
            key = it["name"].lower()
            if key in seen:
                continue
            seen.add(key)
            it["updated"] = p["time"]
            items.append(it)
    items.sort(key=lambda x: ([c for c, _ in CATEGORIES] + ["Другое"]).index(x["category"]))
    return {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "count": len(items), "items": items}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", help="разобрать сохранённый пост из файла вместо канала")
    args = ap.parse_args()

    if args.text:
        data = build([{"id": "local", "time": None, "text": Path(args.text).read_text(encoding="utf-8")}])
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    if not CHANNEL or not MARKUP:
        print("Не заданы секреты SOURCE_CHANNEL и MARKUP.", file=sys.stderr)
        return 1
    data = build(fetch_posts())
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"count": 0}
    if data["count"] == 0 or (prev.get("count") and data["count"] < prev["count"] * MAX_DROP):
        print(f"Подозрительно мало позиций: {data['count']} (было {prev.get('count')}). Прайс не обновлён.", file=sys.stderr)
        return 1  # запуск упадёт, GitHub пришлёт письмо
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Сохранено позиций: {data['count']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
