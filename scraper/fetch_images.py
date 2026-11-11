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

import io

import requests
import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ROOT = pathlib.Path(__file__).resolve().parent.parent
CDN = "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/{name}?wid=2600&fmt=png-alpha"

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
    "orange": ["cosmicorange"], "blue": ["deepblue", "mistblue", "skyblue", "ultramarine", "blue", "bluetitanium"],
    "natural": ["naturaltitanium"], "bluetitanium": ["bluetitanium"], "desert": ["deserttitanium"], "black": ["black", "blacktitanium", "spaceblack"],
    "white": ["white", "whitetitanium", "cloudwhite"], "gold": ["lightgold", "gold"], "silver": ["silver"],
    "purple": ["purple", "deeppurple"], "red": ["productred", "product-red", "red"], "deser": ["deserttitanium"], "pink": ["pink", "softpink", "lightpink", "blush", "pastelpink"], "glacier": ["glacier", "glacierblue"],
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


def unbg(im: Image.Image, thresh: int = 9) -> Image.Image:
    """Убирает ровный фон фото Apple: всё, что похоже на цвет фона и связано с краем кадра.
    Белые и серебристые корпуса не страдают — светлые места внутри контура техники с краем не связаны."""
    rgb = np.asarray(im.convert("RGB")).astype(np.int16)
    ref = np.median(rgb[3, rgb.shape[1] // 4: rgb.shape[1] * 3 // 4], axis=0)   # цвет фона: середина верхней кромки
    similar = np.abs(rgb - ref).sum(axis=2) <= thresh
    labels, _ = ndimage.label(similar)
    edge = np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]]))
    bg = np.isin(labels, edge[edge > 0])
    alpha = Image.fromarray((~bg * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    out = im.convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def cutout(body: bytes, path: pathlib.Path, height: int) -> str:
    """Фото Apple → прозрачный фон → обрезка по контуру → WebP."""
    im = Image.open(io.BytesIO(body)).convert("RGBA")
    box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if box:
        im = im.crop(box)                         # убрали прозрачные поля вокруг плитки
    alpha = np.asarray(im.getchannel("A"))
    clear = (alpha < 16).mean() > 0.15           # фон действительно прозрачный, а не только уголки плитки
    if not clear:
        px = np.asarray(im)
        ref = np.median(px[3, im.width // 4: im.width * 3 // 4, :3], axis=0)
        flat = Image.new("RGBA", im.size, tuple(int(v) for v in ref) + (255,))
        flat.alpha_composite(im)                 # скруглённые уголки плитки заливаем её же фоном
        im = unbg(flat)
        box = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if box:
            pad = 8
            im = im.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(im.width, box[2] + pad), min(im.height, box[3] + pad)))
    if im.height > height:
        im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=86, method=6)
    return "прозрачный" if clear else "фон убран"


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
    path = ROOT / "img/apple" / re.sub(r"\W+", "-", model.lower()) / f"{color.replace(' ', '-')}.webp"
    if path.exists():
        return model, color, path, "есть"
    for name in candidates(model, color):
        body = try_get(CDN.format(name=name))
        if body:
            how = cutout(body, path, 1000)
            return model, color, path, f"{name} ({how})"
    return model, color, None, "не найдено"


# Картинки категорий из меню магазина Apple: «store-card-13-<категория>-nav-<год><месяц>»
NAV = {"iPhone": "iphone", "Mac": "mac", "iPad": "ipad", "Apple Watch": "watch", "AirPods": "airpods", "Аксессуары Apple": "accessories"}
NAV_CDN = "https://store.storeimages.cdn-apple.com/4982/as-images.apple.com/is/{name}?wid=1400&fmt=png-alpha"


def find_nav(item):
    cat, key = item
    path = ROOT / "img/apple/nav" / f"{key}.webp"
    if path.exists():
        return cat, path, "есть"
    for year in range(2026, 2021, -1):
        for month in range(12, 0, -1):
            name = f"store-card-13-{key}-nav-{year}{month:02d}"
            body = try_get(NAV_CDN.format(name=name))
            if body:
                how = cutout(body, path, 640)
                return cat, path, f"{name} ({how})"
    return cat, None, "не найдено"


def main():
    jobs = [(m, c) for m, cs in model_colors().items() for c in sorted(cs)]
    found = {}
    with ThreadPoolExecutor(8) as ex:
        for model, color, path, how in ex.map(find, jobs):
            print(f"{model:20} {color:12} {how}")
            if path:
                found[f"{model}|{color}"] = str(path.relative_to(ROOT))
    with ThreadPoolExecutor(6) as ex:
        for cat, path, how in ex.map(find_nav, NAV.items()):
            print(f"категория {cat:16} {how}")
            if path:
                found[f"nav|{cat}"] = str(path.relative_to(ROOT))
    (ROOT / "data/images.json").write_text(json.dumps(found, ensure_ascii=False, indent=1, sort_keys=True))
    print(f"найдено {len(found)} из {len(jobs)}")


if __name__ == "__main__":
    main()
