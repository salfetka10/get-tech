# get.tech

Страница get.tech и прайс, который обновляется из открытого канала поставщика. Канал и наценка лежат в секретах репозитория (Settings → Secrets and variables → Actions): `SOURCE_CHANNEL`, `MARKUP`, `PACKAGING`.

- `index.html` — страница get.tech. Если рядом есть `data/prices.json`, показывает живой прайс, иначе примеры.
- `scraper/fetch_prices.py` — читает канал, считает цену get.tech (цена поставщика + наценка, вверх до 100 ₽), пишет `data/prices.json`. Цены поставщика в файл не попадают.
- `.github/workflows/prices.yml` — запускает скрипт каждые 30 минут и сохраняет прайс, если он изменился.

## Запуск

1. Settings → Pages → Source: «Deploy from a branch», ветка `main`, папка `/ (root)`. Через минуту страница откроется по адресу `https://<аккаунт>.github.io/<репозиторий>/`.
2. Actions → «Прайс get.tech» → Run workflow. Первый запуск создаст `data/prices.json`.
3. Если запуск упал, GitHub пришлёт письмо. Чаще всего это значит, что поставщик изменил формат постов или закрыл веб-версию канала: прайс на сайте останется прежним.

## Настройки

В начале `scraper/fetch_prices.py`: канал, наценка, округление, упаковка, сколько постов читать.

Проверить разбор на тексте поста: `python scraper/fetch_prices.py --text tests/sample_post.txt`
