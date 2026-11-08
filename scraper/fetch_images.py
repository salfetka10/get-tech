"""Фото техники для карточек get.tech.

Берёт модели и цвета iPhone из data/prices.json, ищет официальное фото цвета на CDN Apple
по известному шаблону адреса и сохраняет в img/apple/<модель>/<цвет>.jpg.
Карта найденных фото: data/images.json («iPhone 18 Pro|black» → путь).
Фото, которые уже скачаны, не перекачиваются. Запуск: python scraper/fetch_images.py
"""
import json
import pathlib
import re
from concurrent.futures import ThreadPoolExecutor

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CDN = "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/{name}?wid=900&hei=900&fmt=jpeg&qlt=90"

# модель → (код на CDN, месяцы выхода, размер экрана в названии файла)
MODELS = {
    "iPhone 18 Pro": ("iphone-18-pro", ["202609", "202610"], "6-3inch"),
    "iPhone 18 Pro Max": ("iphone-18-pro", ["202609", "202610"], "6-9inch"),
    "iPhone 17 Pro": ("iphone-17-pro", ["202509"], "6-3inch"),
    "iPhone 17 Pro Max": ("iphone-17-pro", ["202509"], "6-9inch"),
    "iPhone 17": ("iphone-17", ["202509"], "6-3inch"),
    "iPhone Air": ("iphone-air", ["202509"], ""),
    "iPhone 17e": ("iphone-17e", ["202602", "202603", "202602-6-1inch"], "6-1inch"),
    "iPhone 16 Pro": ("iphone-16-pro", ["202409"], "6-3inch"),
    "iPhone 16 Pro Max": ("iphone-16-pro", ["202409"], "6-9inch"),
    "iPhone 16": ("iphone-16", ["202409"], "6-1inch"),
    "iPhone 16 Plus": ("iphone-16", ["202409"], "6-7inch"),
    "iPhone 16e": ("iphone-16e", ["202502"], "6-1inch"),
    "iPhone 15 Pro": ("iphone-15-pro", ["202309"], "6-1inch"),
    "iPhone 15 Pro Max": ("iphone-15-pro", ["202309"], "6-7inch"),
    "iPhone 15": ("iphone-15", ["202309"], "6-1inch"),
    "iPhone 15 Plus": ("iphone-15", ["202309"], "6-7inch"),
    "iPhone 14": ("iphone-14", ["202209"], "6-1inch"),
    "iPhone 14 Plus": ("iphone-14", ["202209"], "6-7inch"),
    "iPhone 14 Pro Max": ("iphone-14-pro", ["202209"], "6-7inch"),
    "iPhone 13": ("iphone-13", ["202207", "202203", "202109"], "6-1inch"),
}
# как поставщик пишет цвет → как Apple называет его в адресе
ALIASES = {
    "orange": ["cosmicorange"], "blue": ["deepblue", "mistblue", "skyblue", "ultramarine", "blue"],
    "natural": ["naturaltitanium"], "desert": ["deserttitanium"], "black": ["black", "blacktitanium", "spaceblack"],
    "white": ["white", "whitetitanium", "cloudwhite"], "gold": ["lightgold", "gold"], "silver": ["silver"],
    "purple": ["purple", "deeppurple"], "pink": ["pink", "softpink"], "glacier": ["glacier", "glacierblue"],
}

HOMO = str.maketrans("аеорсхуАЕОРСХ", "aeopcxyAEOPCX")


def norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.translate(HOMO)).strip()


def model_colors() -> dict:
    data = json.loads((ROOT / "data/prices.json").read_text())
    out = {}
    for x in data["items"]:
        m = re.match(r"(iPhone .*?) (?:64|128|256|512|1TB|2TB)\b\s*([A-Za-z ]*)", norm_name(x["name"]), re.I)
        if not m:
            continue
        model = re.sub(r"\be$", "e", m.group(1)).replace("16E", "16e")
        color = re.sub(r"\b(cpo|esim|e sim)\b", "", m.group(2), flags=re.I).strip().lower()
        if model in MODELS and color:
            out.setdefault(model, set()).add(color)
    return out


def candidates(model: str, color: str) -> list[str]:
    slug, months, size = MODELS[model]
    names = []
    for c in ALIASES.get(color, []) + [color.replace(" ", "")]:
        for ym in months:
            for s in ([size, ""] if size else [""]):
                names.append(f"{slug}-finish-select-{ym}-{s + '-' if s else ''}{c}")
    return list(dict.fromkeys(names))


def try_get(url: str):
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image") and len(r.content) > 8000:
            return r.content
    except requests.RequestException:
        pass
    return None


def find(job):
    model, color = job
    path = ROOT / "img/apple" / re.sub(r"\W+", "-", model.lower()) / f"{color.replace(' ', '-')}.jpg"
    if path.exists():
        return model, color, path, "есть"
    for name in candidates(model, color):
        body = try_get(CDN.format(name=name))
        if body:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            return model, color, path, name
    return model, color, None, "не найдено"


def main():
    jobs = [(m, c) for m, cs in model_colors().items() for c in sorted(cs)]
    found = {}
    with ThreadPoolExecutor(8) as ex:
        for model, color, path, how in ex.map(find, jobs):
            print(f"{model:20} {color:12} {how}")
            if path:
                found[f"{model}|{color}"] = str(path.relative_to(ROOT))
    (ROOT / "data/images.json").write_text(json.dumps(found, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"найдено {len(found)} из {len(jobs)}")


if __name__ == "__main__":
    main()
