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
POSTS_TO_READ = 5000   # поставщик правит старые посты, поэтому читаем канал целиком
MIN_PRICE, MAX_PRICE = 1_000, 1_500_000
MAX_DROP = 0.5         # если позиций стало меньше половины прошлого раза, не обновляем

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "prices.json"

# Категории: первое совпадение по строке позиции вместе с заголовком блока. Порядок важен.
CATEGORIES = [
    ("iPhone", r"iphone"),
    ("Mac", r"macbook|imac|mac ?mini|mac ?studio|mac ?pro"),
    ("iPad", r"ipad"),
    ("Apple Watch", r"apple watch|(?<!galaxy )(?<!redmi )watch (ultra|series|se)\b"),
    ("AirPods", r"airpods"),
    ("Аксессуары Apple", r"magic (mouse|keyboard|trackpad)|apple pencil|airtag|magsafe|apple tv|homepod|vision pro"),
    ("Смартфоны", r"galaxy [asz]\d|galaxy z|samsung galaxy (?!tab|book|watch|buds)|redmi|poco|xiaomi \d|pixel \d|honor (?!magicbook|pad)|realme|oneplus|nothing phone|huawei (pura|mate|nova|p\d)|смартфон"),
    ("Планшеты", r"galaxy tab|matepad|xiaomi pad|redmi pad|honor pad|планшет|lenovo tab"),
    ("Ноутбуки", r"galaxy book|ноутбук|notebook|thinkpad|vivobook|zenbook|ideapad|legion|\brog\b|tuf gaming|matebook|magicbook|aspire|predator|nitro|pavilion|victus|omen|inspiron|xps|yoga"),
    ("Телевизоры", r"^\d{2,3}\" |телевизор|\btv\b|oled\d|qled"),
    ("Игровые приставки", r"playstation|\bps5\b|xbox|nintendo|switch 2|steam deck|dualsense"),
    ("Наушники и колонки", r"buds|наушник|jbl|marshall|\bwh-|\bwf-|колонк|beats|станция|soundbar|саундбар"),
    ("Часы и браслеты", r"watch|band \d|часы|garmin|fenix|forerunner|quatix|instinct|venu|epix|amazfit"),
    ("Фото и видео", r"gopro|\bdji\b|insta360|фотоаппарат|камера|объектив|eos|alpha a\d|fujifilm"),
    ("Красота и дом", r"dyson|пылесос|робот|фен\b|стайлер|air fryer|аэрогрил|очиститель|purifier|парогенератор|karcher|утюг|чайник|кофемашин|блендер|мультиварк|увлажнител"),
    ("Принтеры и расходники", r"принтер|мфу|pixma|i-sensys|laserjet|deskjet|smart tank|officejet|ecosys|pantum|xerox|\bepson\b|картридж|тонер|profiline|tsc "),
    ("Комплектующие", r"geforce|\brtx\b|radeon|socket|ddr\d|материнск|блок питания|\d{3,4}w |процессор|ryzen|core i\d|core ultra|кулер|корпус"),
    ("Накопители", r"\bssd\b|\bhdd\b|sata|nvme|m\.2|флешк|\busb-?c?\b.*\d+ ?(gb|tb)|^\d+ ?(gb|tb) |kingston|netac|sandisk|samsung t\d"),
    ("Мониторы и сеть", r"монитор|ubiquiti|роутер|router|keenetic|tp-link|mikrotik|точка доступа|mesh"),
]
CATEGORY_ORDER = [c for c, _ in CATEGORIES] + ["Другое"]

# цена: «-117.000» внутри строки (дальше могут быть флаги и пометки) или число в конце строки
PRICE_DASH_RE = re.compile(r"[-–—:=]\s*(\d{1,3}(?:[ .,  ]\d{3})+)(?!\d)")
PRICE_END_RE = re.compile(r"(\d{1,3}(?:[ .,  ]\d{3})+|\d{4,7})\s*(?:₽|р\.?|руб\.?)?\s*$", re.I)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


SKU_RE = re.compile(r"\[[A-Z0-9/-]{4,}\]-?|^art:\s*[\d-]+", re.I)   # артикулы поставщика: [Z1EK000TE], Art: 010-02904-00
SKIP_RE = re.compile(r"гаранти|год выпуска|замена|ремонт|доставк|скидк|левое ухо|правое ухо|\bbox\b|кейс отдельно", re.I)


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


def regions(text: str) -> str:
    """Флаги стран → коды через запятую (KR, HK). Для iPhone от региона зависят SIM и eSIM."""
    codes = ["".join(chr(ord(c) - 0x1F1E6 + 65) for c in f) for f in FLAG_RE.findall(text)]
    return ", ".join(dict.fromkeys(codes))


def clean(line: str) -> str:
    line = FLAG_RE.sub(" ", line)
    line = EMOJI_RE.sub(" ", line)
    line = re.sub(r"[\-–—:=|•·]+\s*$", "", line)
    return re.sub(r"\s+", " ", line).strip(" -–—:=|•·")


def note(tail: str) -> str:
    """Пометки после цены: тип SIM, «актив» и т. п."""
    t = clean(tail).strip("() ")
    t = re.sub(r"\)\s*\(", ", ", t).replace("(", " ").replace(")", " ")
    t = re.sub(r"([a-z])([а-яё])", r"\1 \2", t, flags=re.I)
    t = re.sub(r"\b1 ?sim ?\+ ?e ?sim\b", "SIM + eSIM", t, flags=re.I)
    t = re.sub(r"\be ?sim\b", "eSIM", t, flags=re.I)
    t = re.sub(r"\bактив\w*", "активирован", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" ,*₽")
    return t if re.search(r"[a-zа-я]", t, re.I) else ""


def join_name(header: str, line: str) -> str:
    """«iPhone 18 Pro 256/512/1TB» + «18 Pro 256 Black» → «iPhone 18 Pro 256 Black»."""
    if not header:
        return line
    words = [w for w in header.split() if "/" not in w]
    first = line.split()[0].lower() if line.split() else ""
    for i, w in enumerate(words):
        if w.lower() == first:
            return " ".join(words[:i] + [line])
    if header.lower() in line.lower():
        return line
    return " ".join(words + [line])


def parse_post(text: str) -> list[dict]:
    """Строка с ценой = позиция. Строка без цены = заголовок блока для следующих строк."""
    items, header = [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = PRICE_DASH_RE.search(line) or PRICE_END_RE.search(line)
        if not m:
            h = clean(line)
            if len(h) >= 3 and re.search(r"[a-zа-я]", h, re.I):
                header = h
            continue
        price = to_rub(m.group(1))
        if not MIN_PRICE <= price <= MAX_PRICE:
            continue
        head = clean(SKU_RE.sub(" ", line[: m.start()]))
        if not head or SKIP_RE.search(head):
            continue
        own = category(head) != "Другое"
        name = head if own else join_name(header, head)
        items.append({
            "category": category(name) if own else category(name + " " + header),
            "name": name,
            "region": regions(line),
            "note": note(line[m.end():]),
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
            photos = [re.search(r"url\('([^']+)'\)", ph.get("style", "")) for ph in m.select(".tgme_widget_message_photo_wrap")]
            photos = [x.group(1) for x in photos if x]
            text = ""
            if body:
                for br in body.find_all("br"):
                    br.replace_with("\n")
                text = body.get_text()
            if text or photos:
                posts.append({"id": m.get("data-post", ""), "time": when["datetime"] if when else None,
                              "text": text, "photos": photos})
        ids = [int(m.get("data-post", "0").split("/")[-1] or 0) for m in found]
        before = min(ids) if ids else None
        if not before:
            break
    return posts


MEDIA: list[str] = []
DIAG: dict = {}


def fetch_posts_api() -> list[dict]:
    """Чтение канала от имени технического аккаунта: видит все посты, включая те,
    что веб-версия не показывает («Please open Telegram to view this post»)."""
    import asyncio
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    async def run():
        posts = []
        async with TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]),
                                  os.environ["TG_API_HASH"]) as client:
            async for msg in client.iter_messages(CHANNEL, limit=POSTS_TO_READ):
                if not msg.message and msg.media:
                    MEDIA.append(f"{msg.id}:{type(msg.media).__name__}")
                if msg.message:
                    when = (msg.edit_date or msg.date)
                    posts.append({"id": f"{CHANNEL}/{msg.id}", "time": when.isoformat(), "text": msg.message, "photos": []})
            one = await client.get_messages(CHANNEL, ids=12970)
            if one:
                d = one.to_dict()
                DIAG.update({k: (type(v).__name__ if not isinstance(v, dict) else "dict:" + str(v.get("_"))) for k, v in d.items() if v not in (None, False, [], "")})
                DIAG["message_len"] = len(one.message or "")
                DIAG["raw_text_len"] = len(one.raw_text or "")
        return posts

    return asyncio.run(run())


def fetch_single(num: int) -> dict | None:
    """Один пост по номеру через встраиваемую версию. Нужна, если пост не попал в ленту t.me/s."""
    import requests
    from bs4 import BeautifulSoup

    r = requests.get(f"https://t.me/{CHANNEL}/{num}", params={"embed": "1", "mode": "tme"}, timeout=30,
                     headers={"User-Agent": "get-tech-price/1.0"})
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    body = soup.select_one(".tgme_widget_message_text")
    if not body:
        return None
    for br in body.find_all("br"):
        br.replace_with("\n")
    when = soup.select_one("time[datetime]")
    return {"id": f"{CHANNEL}/{num}", "time": when["datetime"] if when else None, "text": body.get_text(), "photos": []}


def build(posts: list[dict]) -> dict:
    # новые посты важнее старых: одна и та же позиция берётся из самого свежего поста
    posts = sorted(posts, key=lambda p: p["time"] or "", reverse=True)
    seen, items = set(), []
    for p in posts:
        for it in parse_post(p["text"]):
            key = (it["name"] + "|" + it["region"] + "|" + it["note"]).lower()
            if key in seen:
                continue
            seen.add(key)
            it["updated"] = p["time"]
            items.append(it)
    items.sort(key=lambda x: CATEGORY_ORDER.index(x["category"]))
    stats = {"posts": len(posts), "with_prices": sum(1 for p in posts if p["text"] and parse_post(p["text"]))}
    return {"updated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "count": len(items), "stats": stats, "items": items}


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
    if os.environ.get("TG_SESSION"):
        posts = fetch_posts_api()
        data = build(posts)
        data["stats"]["source"] = "api"
        data["stats"]["media_without_text"] = MEDIA[:60]
        data["stats"]["diag_12970"] = DIAG
        return save(data)
    posts = fetch_posts()
    seen = {int(p["id"].split("/")[-1] or 0) for p in posts}
    probe = {}
    for num in range(max(seen) + 1, max(seen) + 40) if seen else []:   # свежие посты, которых ещё нет в ленте
        one = fetch_single(num)
        probe[num] = bool(one)
        if one:
            posts.append(one)
    data = build(posts)
    data["stats"]["probe"] = {k: v for k, v in probe.items() if v}
    data["stats"]["feed_max_id"] = max(seen) if seen else None

    data["stats"]["source"] = "web"
    return save(data)


def save(data: dict) -> int:
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
