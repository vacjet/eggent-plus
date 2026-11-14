# Образ с инструментами документов

Слой поверх базового образа: `tesseract` с русским языком, `ghostscript`, `pandoc`,
`poppler-utils`, `libreoffice` (writer, calc, impress, русская локализация) и `python3-matplotlib`
с DejaVu для кириллицы в подписях. Без них агент не разбирает сканы, не конвертирует docx в PDF и
не строит графики из коробки.

## Сборка (LXC <номер>, `<ip сборщика>`)

```bash
ssh -i <каталог ключей>/<ключ сборщика> root@<ip сборщика>
cd /root/eggent-plus/upstream
docker build -t eggent-plus:base .
docker build -f /root/eggent-plus/docker/Dockerfile -t eggent-plus:documents .
```

Не на VM <номер>: там живой Eggent и 2 ГБ свободной памяти.

## Развёртывание тестового экземпляра из репозитория

```bash
./docker/deploy-test.sh                 # порт 3100, данные в testdata-ru
./docker/deploy-test.sh /root/eggent-plus 3101
```

Скрипт берёт тег из `.github/workflows/patches.yml`, накладывает все патчи на чистый клон,
собирает образ и **заменяет** контейнер, оставляя данные: вход, настройки и модели переживают
пересборку. Это единственный способ увидеть правку на `:3100` — контейнер запускает собранное
приложение (`next start`), горячей перезагрузки там нет.

## Почта вместе со стендом

Если рядом с репозиторием лежит `mail-data/accounts.json` и `mail-data/adapter.env` (права **600**),
`deploy-test.sh` сам поднимает `mail-adapter` на хосте и передаёт контейнеру
`EGGENT_EMAIL_API_URL=http://host.docker.internal:8787`. В `adapter.env`:

```
EGGENT_MAIL_ADAPTER_TOKEN=<токен, 32+ символа>
EGGENT_EMAIL_ADDRESS=mail@example.com
```

Пароль ящика — в `mail-data/secrets/<id>` (600), не в `adapter.env` и не в `accounts.json`.
Смотри `mail-adapter/README.md`.

## Приёмка

```bash
docker run --rm eggent-plus:documents sh -lc \
  'tesseract --list-langs | grep -qx rus && pandoc --version | head -1 && soffice --version && gs --version'
docker run -d --name eggent-docs -p 3101:3000 -v /root/eggent-plus/testdata-docs:/app/data eggent-plus:documents
docker exec eggent-docs node -e 'fetch("http://127.0.0.1:3000/api/health").then(r=>console.log(r.status))'
```

Проверенный результат 13.11.2026: `eng osd rus` у tesseract, pandoc 2.17, ghostscript 10.00.0,
poppler 22.12.0, docx→PDF через `soffice`, matplotlib рисует кириллицу и tesseract читает её обратно
из PNG; приложение на `:3101` отвечает `health 200`.

Dockerfile сам проверяет инструменты на этапе сборки (tesseract читает русский список языков,
`gs` делает PDF из PostScript, `pdftoppm` превращает его в PNG), поэтому «собралось, но не работает»
видно сразу, а не в чате.

Размер: базовый образ 3.64 ГБ плюс примерно 400–450 МБ инструментов.

Грабли: `python3` в образе — это venv приложения (`/opt/eggent-python`, numpy 2.4), поэтому
`python3-matplotlib` из apt не годится: он собран под системный numpy и падает на импорте.
matplotlib ставится в venv через pip.
