# Память линии eggent-plus

Устойчивые факты. Не журнал: события и ход работ — в `docs/handoff.md` и коммитах.

## Продукт

- Сборка называется **eggent-plus**, выдаётся за неофициальную; теги релизов `plus-<upstream>-<n>`.
- Upstream — `github.com/eggent-ai/eggent`, MIT, рабочий тег **v0.8.0** (`f869e0b`).
- В теге `src/i18n/messages.ts` — **1864 строки**; в `main` уже 2059, поэтому переводим по тегу.
- Стратегия: `main` = зеркало upstream (только fast-forward), `our` = патчи поверх тега.
- Патчи ядра ограничены списком `TOUCHED.md`. Всё остальное — конфиг, скиллы, расширения, `data/`.
- В upstream только английский (`SUPPORTED_LOCALES = ["en"]`); русского перевода нет ни в коде,
  ни в сборке. Перевод пишется заново, это первый патч.
- `kb_search` (семантический поиск по файлам проекта) в 0.8.0 есть, но выдан только публичным шарам —
  `src/lib/pi/public-share.ts:32`.
- Русская локаль: `src/i18n/messages.ru.ts` — **1770 ключей** (в файле upstream 1864 строки, из них
  1770 записей словаря). Регистрация — две строки в `messages.ts`, импорт через `@/i18n/messages.ru`.
- `DEFAULT_LOCALE = "ru"`: папка вложений почты называется «Сообщения», поэтому upstream-тесты
  `test:mail`/`test:email` (ждут `Messages/...`) прогонять с `EGGENT_DEFAULT_LANGUAGE=en`
  (проверено: без него `test:mail` 20 проверок / 5 падений, с ним 20/20).
- Словарь намерений двуязычный; `INTERRUPT_VERBS` — формы с `(?!л)`, иначе «остановился» читается
  как приказ убить процесс. Тест upstream `npm run -s test:vocabulary` проверяет это и русский.

- Репозиторий: `github.com/<owner>/eggent-plus`, **публичный** (решение 30 — поэтому секретов
  и данных заказчика в нём нет), ветка **main**; remote
  `git@github.com-<alias>:<owner>/eggent-plus.git`, ключ `<каталог ключей>/<ключ репозитория>`,
  алиас в `~/.ssh/config`. CI (`.github/workflows/patches.yml`) включён, прогоны видны только владельцу.

- Почта на стенде: `mail-adapter` на сборщике (`:8787`, `host.docker.internal`), ящик
  `user@example.com`; секреты в `/root/eggent-plus/mail-data` (600, вне репозитория), перезапуск —
  `/root/mail-adapter-start.sh`.

## CI

- Node в `.github/workflows/patches.yml` зафиксирован `actions/setup-node@v4` версией 22: без этого
  на раннере остаётся Node 20, а тесты upstream вызывают `--experimental-strip-types` (с 22.6), и
  job падает до сборки. `scripts/check-workflow.py` проверяет это и умеет падать.
- Сборка локально воспроизводится только с devDependencies: в контейнере воркспейса
  `NODE_ENV=production`, поэтому `npm ci` пропускает их и Next падает на `@tailwindcss/postcss`.
  Правильно: `env -u NODE_ENV npm ci && npm run build`.

## Окружение

- Воркспейс: `/app/data`, этот репозиторий — `/app/data/projects/eggent-plus`.
- Сборщик: **LXC <номер> `build-eggent-plus`**, `<ip сборщика>`, Debian 13, 2 ядра, 4 ГБ RAM, 32 ГБ,
  Docker 26.1.5. Ключ: `<каталог ключей>/<ключ сборщика>`.
- На сборщике: `/root/eggent-plus/upstream` — клон v0.8.0, ветка `our`;
  образ `eggent-plus:base` (3.64 ГБ), тестовый контейнер `eggent-test` на `:3100`.
- Debian 13: пакет `docker.io` — только демон; CLI ставится отдельно (`docker-cli`,
  `docker-buildx`, `docker-compose`).
- Живой Eggent: VM <номер> `eggent` (`<ip живого экземпляра>`), Docker 29.9.3, compose в `/home/eggent/eggent`,
  образ `eggent:stream-test`, данные `/home/eggent/eggent/data`. Не трогать без задачи.
- Proxmox: `root@<ip proxmox>`, ключ `~/.ssh/<ключ proxmox>` (ключ `<ключ proxmox>` не пускает).
- Сборка базового образа на слабом хосте — около 6–7 минут.
- Тестовые экземпляры на сборщике: `eggent-ru` — `http://<ip сборщика>:3100`, данные
  `/root/eggent-plus/testdata-ru`; `eggent-docs` — `:3101`, данные `testdata-docs`. Вход по умолчанию
  `admin/admin`, при первом входе Eggent требует заменить учётные данные.
- Образ с инструментами документов: `docker/Dockerfile` поверх `eggent-plus:base`, на сборщике
  `docker build -f .../docker/Dockerfile -t eggent-plus:documents .`.
- Проверки локали: `python3 scripts/check-i18n.py` (снимок en — `tests/i18n/en-reference.json`),
  `--self-test`, и `cd upstream && npm run -s test:vocabulary`.

## Внешние источники (этап 4)

- Скилл `skills/external-sources/` в репозитории; ставится в данные экземпляра
  (`data/projects/<id>/skills/external-sources/`) скриптом `scripts/install-skills.sh`. Ядро не патешно.
- Скрипты без зависимостей (stdlib): `site_audit.py` (robots, sitemap, коды страниц) и
  `yandex_read.py` (Метрика, Вебмастер, Директ). Данные — `data/external/`, статус — `status.json`.
- Коды возврата — часть контракта: `0` ok, `1` источник недоступен, `3` ошибка авторизации (401/403).
- Токены: `YANDEX_SEO_TOKEN` (Метрика + Вебмастер), `YANDEX_DIRECT_TOKEN` (Директ); в воркспейсе
  лежат в `/app/data/projects/toolbox/secrets.env` (600). В скилл и в отчёт они не попадают.
- API проверены живым чтением: Метрика и Вебмастер отвечают, Директ отдаёт кампании; `Cost` в
  отчёте Директа — микроединицы (делится на 1 000 000).
- Стенд `:3100` (`testdata-ru`): проект `2ee6c1c7`, расписания — `data/scripts/schedules.json`,
  журнал — `runs.jsonl`, тик — 30 с, первый тик через 5 с после старта.
- Каталог `data/scripts` обязан принадлежать uid 1000 (как остальные данные): созданный руками
  под root он даёт `EACCES ... runs.jsonl` в `docker logs`, и задание молча не запускается.

## Предпочтения владельца

- Во время длинной работы нужны короткие статусы в чате: молчание читается как «завис».
- В UI хочет видимый индикатор состояния агента: работает / ошибка / ждёт ответа (цвет или значок).
  Это идея на будущие апдейты продукта, не задача текущего этапа.
