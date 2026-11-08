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
    ("Чехлы и аксессуары", r"\bcase\b|чехол|strap|ремеш|стекло|плёнк|пленк|кабель|cable|адаптер|adapter|зарядн|charger|power ?bank|magsafe (?!battery)|подставк|держател|travel bag|\bблок\b"),
    ("Аксессуары Apple", r"magic (mouse|keyboard|trackpad)|apple pencil|airtag|magsafe|apple tv|homepod|vision pro"),
    ("iPhone", r"iphone|^1[1-9](e| ?pro max| ?pro| ?plus| ?mini| ?air)? \d{1,4} ?(gb|tb)?\b|^air (1|2)?\d{2,3}gb|^iphone"),
    ("Mac", r"macbook|imac|mac ?mini|mac ?studio|mac ?pro|^(air|pro) 1[3-6]\b|studio display|pro display|pro stand"),
    ("iPad", r"ipad"),
    ("Apple Watch", r"apple watch|(?<!galaxy )(?<!redmi )watch (ultra|series|se)\b|^watch (se )?\d|ultra \d 49|milanese|alpine loop|trail loop|ocean band|sport (band|loop)|\baw s\d|^s1\d 4\d"),
    ("AirPods", r"airpods"),
    ("Смартфоны", r"galaxy [asz]\d|galaxy z|samsung galaxy (?!tab|book|watch|buds)|^(s2\d|a\d{2}s?|z ?(flip|fold) ?\d)|redmi(?! pad| watch| buds)|poco|xiaomi \d|pixel \d|honor (?!magicbook|pad|watch)|realme|oneplus(?! watch)|nothing phone|huawei (pura|mate|nova|p\d)|vivo|oppo|смартфон"),
    ("Планшеты", r"galaxy tab|samsung tab|matepad|xiaomi pad|redmi pad|honor pad|планшет|lenovo tab|kindle|электронн\w* книг"),
    ("Ноутбуки", r"galaxy book|ноутбук|notebook|thinkpad|vivobook|zenbook|ideapad|legion|\brog\b|tuf gaming|matebook|magicbook|aspire|predator|nitro|pavilion|victus|omen|inspiron|xps|yoga|ryzen \d \d{4}[uh]|core (ultra )?\d \d{3}[uhv]|\bmsi\b|\basus\b|thinkbook|expertbook|proart|gigabyte (gaming|aero|aorus)|katana|cyborg|raider"),
    ("Телевизоры и проекторы", r"^\d{2,3}\" |телевизор|\btv\b|oled\d|qled|проектор|projector"),
    ("Игровые приставки", r"playstation|\bps5\b|\bps disk|xbox|nintendo|switch 2|steam deck|dualsense|logitech g\d{2}\b|руль"),
    ("Наушники и колонки", r"buds|наушник|jbl|marshall|\bwh-|\bwf-|колонк|beats|станция|soundbar|саундбар|bose|bowers|harman|sonos|\bb&o\b|sennheiser|logitech z\d"),
    ("Часы и браслеты", r"watch|band \d|часы|garmin|fenix|forerunner|quatix|instinct|venu|epix|amazfit|marq|tactix|descent|vivosmart|vivoactive|index s2|fitbit|kospet|whoop|approach s\d|hrm"),
    ("Фото и видео", r"gopro|\bdji\b|insta360|фотоаппарат|камера|объектив|eos|alpha a\d|fujifilm|instax"),
    ("Гаджеты", r"умные очки|ray-ban|oakley meta|meta quest|ledger|криптокошел|датчик|умн\w* (розетк|лампа|дом)|яндекс"),
    ("Красота и уход", r"dyson|фен\b|стайлер|\bhs0\d|airwrap|supersonic|medicube|массаж|эпилятор|бритв|триммер для|маска"),
    ("Дом и кухня", r"пылесос|робот|air fryer|аэрогрил|очиститель|purifier|парогенератор|karcher|утюг|чайник|кофемашин|блендер|мультиварк|увлажнител|холодильник|стиральн|сушильн|посудомо|варочн|духов|вытяжк|кондиционер|сплит|водонагрев|\bewh\b|\brwh\b|\bgwh\b|\bbwh\b|bosch b[gw][cd]|обогрев|тепловая пушк|тепловые пушки|heater|вентилятор|fan\b|биокамин|микроволн|плит"),
    ("Сад и инструмент", r"denzel|champion|makita|edon|deko|газонокос|триммер|культиватор|шуруповерт|дрель|перфоратор|болгар|пила|генератор|мойка высокого"),
    ("Принтеры и расходники", r"принтер|мфу|pixma|i-sensys|laserjet|deskjet|smart tank|officejet|ecosys|pantum|xerox|\bepson\b|картридж|тонер|profiline|tsc "),
    ("Комплектующие", r"geforce|\brtx\b|radeon|socket|ddr\d|материнск|блок питания|\d{3,4}w |процессор|ryzen|core i\d|core ultra|кулер|корпус"),
    ("Накопители", r"\bssd\b|\bhdd\b|sata|nvme|m\.2|флешк|\busb-?c?\b.*\d+ ?(gb|tb)|^\d+ ?(gb|tb) |kingston|netac|sandisk|samsung t\d"),
    ("Мониторы и сеть", r"монитор|ubiquiti|роутер|router|keenetic|tp-link|mikrotik|точка доступа|mesh"),
]
CATEGORY_ORDER = [c for c, _ in CATEGORIES] + ["Другое"]

# цена: «-117.000» внутри строки (дальше могут быть флаги и пометки) или число в конце строки
PRICE_DASH_RE = re.compile(r"(?<!\d)[-–—:=]\s*(\d{1,3}(?:[ .,  ]\d{3})+)(?!\d)")
PRICE_END_RE = re.compile(r"(?<![\d/.,])(\d{1,3}(?:[ .,\u00a0\u202f]\d{3})+|\d{4,7})\s*(?:₽|р\.?|руб\.?)?[\s*!]*$", re.I)
PRICE_ONLY_RE = re.compile(r"^\s*[-–—:=]?\s*(\d{1,3}(?:[ .,\u00a0\u202f]\d{3})+|\d{4,7})\s*(?:₽|р\.?|руб\.?)?[\s*!]*$", re.I)
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]+")
FLAG_RE = re.compile("[\U0001F1E6-\U0001F1FF]{2}")


SKU_RE = re.compile(r"\[[A-Z0-9/-]{4,}\]-?|^art:\s*[\d-]+", re.I)   # артикулы поставщика: [Z1EK000TE], Art: 010-02904-00
SKIP_RE = re.compile(r"гаранти|год выпуска|замена|ремонт|доставк|скидк|левое ухо|правое ухо|\bbox\b|кейс отдельно|месяц|@\w|\+7[\s(]?\d|гравировк|установка|от \d+ ?шт", re.I)
NOISE_RE = re.compile(r"получите дополнительную гарантию от\s*!?|по предзаказу\s*!*|выдача в день заказа[^‼]*‼?|\bnew\b|\"new\"|новинка", re.I)


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


BRANDS = {"iphone": "iPhone", "ipad": "iPad", "macbook": "MacBook", "imac": "iMac", "airpods": "AirPods",
          "airtag": "AirTag", "magsafe": "MagSafe", "pro": "Pro", "max": "Max", "air": "Air", "mini": "mini", "plus": "Plus"}


def pretty(name: str) -> str:
    """«IPHONE 17» → «iPhone 17», «MACBOOK PRO 14» → «MacBook Pro 14»; остальное не трогаем."""
    return re.sub(r"\b[A-Za-z]+\b", lambda m: BRANDS.get(m.group(0).lower(), m.group(0)) if m.group(0).isupper() or m.group(0).lower() in ("iphone", "ipad", "macbook", "airpods") else m.group(0), name)


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


def find_price(line: str):
    """Цена после тире («-117.000🇰🇷 (e sim)») или в конце строки («Cream 79.900*», «— 43500 🇯🇵»)."""
    m = PRICE_DASH_RE.search(line)
    if m:
        return m
    tail = re.sub(r"[\s*!]+$", "", FLAG_RE.sub("", EMOJI_RE.sub("", line)))
    m = PRICE_END_RE.search(tail)
    if m:
        # координаты найденной цены в исходной строке: ищем то же число с конца
        pos = line.rfind(m.group(1))
        return _M(m.group(1), pos, pos + len(m.group(1))) if pos >= 0 else None
    return None


class _M:
    def __init__(self, g, s, e):
        self._g, self._s, self._e = g, s, e
    def group(self, _=1): return self._g
    def start(self): return self._s
    def end(self): return self._e


def parse_post(text: str) -> list[dict]:
    """Строка с ценой = позиция. Строка без цены = заголовок блока для следующих строк.
    Цена может стоять отдельной строкой под названием."""
    items, header, pending = [], "", ""

    def add(head_raw: str, price: int, line: str, after: str):
        head = clean(NOISE_RE.sub(" ", SKU_RE.sub(" ", head_raw)))
        if not head or SKIP_RE.search(head) or not MIN_PRICE <= price <= MAX_PRICE:
            return
        own = category(head) != "Другое"
        name = pretty(head if own else join_name(header, head))
        cat = category(name) if own else category(name + " " + header)
        if cat == "iPhone" and "iphone" not in name.lower():
            name = "iPhone " + name
        if cat == "Mac" and re.match(r"(air|pro) 1[3-6]\b", name, re.I):
            name = "MacBook " + name
        items.append({"category": cat, "name": name, "region": regions(line), "note": note(after), "price": our_price(price)})

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        only = PRICE_ONLY_RE.match(line)
        if only and pending:
            add(pending, to_rub(only.group(1)), pending, "")
            pending = ""
            continue
        m = find_price(line)
        if not m:
            h = clean(NOISE_RE.sub(" ", line))
            if items and "·" in line and len(h) > 10:          # строка характеристик под позицией
                items[-1]["note"] = (items[-1]["note"] + " " + h).strip()[:140]
            elif len(h) >= 3 and re.search(r"[a-zа-я]", h, re.I) and not SKIP_RE.search(h) and not re.fullmatch(r"[\d/. ]+", h):
                header, pending = h, line
            continue
        pending = ""
        add(line[: m.start()], to_rub(m.group(1)), line, line[m.end():])
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


MEDIA: list[int] = []


def rich_inline(node) -> str:
    """Строка из «расширенного» текста Telegram: TextPlain, TextBold, TextConcat, TextCustomEmoji…"""
    if not isinstance(node, dict):
        return node if isinstance(node, str) else ""
    if "texts" in node:
        return "".join(rich_inline(x) for x in node["texts"])
    if "text" in node:
        return rich_inline(node["text"])
    return node.get("alt") or ""


def rich_to_text(rich) -> str:
    """RichMessage (новый формат постов): блоки-абзацы и списки → обычный текст построчно."""
    if not isinstance(rich, dict):
        return ""
    lines = []

    def walk(block):
        if isinstance(block, list):
            for b in block:
                walk(b)
            return
        if not isinstance(block, dict):
            return
        if "text" in block and isinstance(block["text"], dict):
            lines.append(rich_inline(block["text"]))
        for key in ("items", "blocks", "cells", "rows"):
            if key in block:
                walk(block[key])

    walk(rich.get("blocks", []))
    return "\n".join(lines).strip()


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
                text = msg.message or rich_to_text(msg.to_dict().get("rich_message"))
                if not text:
                    if msg.media:
                        MEDIA.append(msg.id)
                    continue
                when = (msg.edit_date or msg.date)
                posts.append({"id": f"{CHANNEL}/{msg.id}", "time": when.isoformat(), "text": text, "photos": []})
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
        data["stats"]["without_text"] = len(MEDIA)
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
