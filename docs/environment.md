# Окружение и сборка

Проверено 13.11.2026.

**Настоящие адреса, имена ключей и ящиков здесь не пишутся** (решение 41): репозиторий публичный.
Они — в приватной заметке воркспейса `notes/eggent-plus-private.md`. Ниже — что где стоит и как
собирать, без адресов.

## Где что стоит

| Что | Значение |
|---|---|
| Proxmox | `root@<ip proxmox>`, ключ `~/.ssh/<ключ proxmox>` (ключ `<ключ proxmox>` не пускает) |
| Хост | домашний сервер: 4 ядра, ~16 ГБ RAM, свободно ~8 ГБ |
| **LXC <номер> `build-eggent-plus`** | **сборщик**: Debian 13, 2 ядра, 4 ГБ RAM, 32 ГБ, IP `<ip сборщика>`, Docker 26.1.5 |
| VM <номер> `eggent` | живой Eggent: Docker 29.9.3, compose в `/home/eggent/eggent`, 5 ГБ RAM, 49 ГБ свободно |
| LXC <номера> | plex / qbittorrent / admin — не наши задачи |
| Каталог сборки (этот репозиторий) | `/app/data/projects/eggent-plus` внутри контейнера Eggent |

## Доступ к сборщику

```bash
ssh -i <каталог ключей>/<ключ сборщика> root@<ip сборщика>
```

Ключ лежит вне репозитория, в `.gitignore` не нуждается. Рабочая копия upstream —
`/root/eggent-plus/upstream` на сборщике (клон тега `v0.8.0`).

## Грабли Debian 13 (важно)

В Debian 13 пакет `docker.io` ставит **только демон** (`dockerd`, `docker-proxy`, `docker-init`).
CLI живёт отдельно:

```bash
apt-get install -y docker.io docker-cli docker-buildx docker-compose
```

Без `docker-cli` команда `docker` не существует, хотя сервис `docker.service` активен.

## Сборка образа

```bash
ssh -i <каталог ключей>/<ключ сборщика> root@<ip сборщика>
cd /root/eggent-plus/upstream
docker build -t eggent-plus:base .
```

На 2 ядрах это долго (Next.js build). Память: 4 ГБ в LXC хватает, в VM <номер> (2 ГБ свободных)
не хватило бы — поэтому сборщик отдельный.

## Где живёт живой Eggent

- Образ `eggent:stream-test` (собран локально 09.11 поверх `eggent:stream-test-base` и
  `ghcr.io/eggent-ai/eggent:0.8.0`), контейнер `eggent-app-1`.
- Compose: `/home/eggent/eggent/docker-compose.yml` + `compose.override.yaml`.
- Данные: `/home/eggent/eggent/data` → в контейнере `/app/data`.
- Исходников на VM нет: только compose, `data/` и `bundled-skills`. Русской локали не сохранилось.

## Цикл правки

1. Правка в клоне на сборщике (`/root/eggent-plus/upstream`, ветка `our`).
2. `git diff > patches/000N-<тема>.patch` и перенос патча в этот репозиторий.
3. `docker build -t eggent-plus:test .` на сборщике.
4. Тестовый экземпляр **не на VM <номер>**, а на сборщике: отдельный каталог данных, порт 3100.
   Живой Eggent не трогаем.
5. `./scripts/apply-patches.sh --check` на чистом теге — патч обязан лечь.

## Проверки

```bash
./check.sh                                  # репозиторий сборки: файлы, секреты, скрипты, локаль
python3 scripts/check-i18n.py               # 1770 ключей ru против снимка en, подстановки
python3 scripts/check-i18n.py --self-test   # валидатор ловит порчу: 6 + 10 негативных кейсов
cd upstream && npm run -s test:vocabulary   # намерения (стоп, расписание, память, инъекции)
```

`test:vocabulary` — тест upstream: он читает `SUPPORTED_LOCALES` и требует русские срабатывания,
когда `ru` включён (`10 checks, 0 failed`). Прогонять после любой правки `vocabulary.ts`.

Когда поднимается тег upstream, снимок английского словаря обновляется отдельно:
`python3 scripts/check-i18n.py --regen-reference upstream/src/i18n/messages.ts` — иначе проверка
будет сверять русский словарь с прошлым тегом.

Сервер: `pct list`, `qm list`, `free -h`, `pvesm status` (через Proxmox).
Живой Eggent: `curl -s http://127.0.0.1:3000/api/health` изнутри контейнера.
