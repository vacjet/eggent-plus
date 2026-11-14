#!/usr/bin/env bash
# Проверка репозитория eggent-plus: обязательные файлы + негативные тесты скриптов.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

missing=0
for f in README.md AGENTS.md context.md memory.md TOUCHED.md .gitignore patches/README.md \
         docs/roadmap.md docs/stage-0-plan.md docs/decisions.md docs/boundaries.md \
         docs/environment.md docs/handoff.md \
         scripts/apply-patches.sh scripts/backup.sh scripts/restore.sh scripts/test-scripts.sh \
         scripts/check-i18n.py scripts/check-touched.py tests/i18n/en-reference.json \
         scripts/install-skills.sh docs/stage-4-plan.md docs/stage-5-plan.md \
         scripts/check-specialists.py scripts/check-private.py \
         scripts/install-template.py scripts/check-templates.py scripts/memory.py \
         skills/typed-memory/SKILL.md docs/stage-6-plan.md \
         templates/seo/template.json templates/seo/project/check.sh \
         templates/seo/project/AGENTS.md templates/seo/README.md \
         bundled-skills/seo/SKILL.md bundled-skills/seo/specialist.json \
         skills/external-sources/SKILL.md skills/external-sources/common.py \
         skills/external-sources/site_audit.py skills/external-sources/yandex_read.py \
         mail-adapter/README.md mail-adapter/adapter/api.py mail-adapter/tests/test_api.py \
         patches/0001-ru-locale.patch patches/0002-image-async.patch \
         patches/0003-script-schedules.patch patches/0004-chat-usage.patch \
         patches/0005-project-usage.patch patches/0006-build-version.patch \
         patches/0007-soft-limit.patch \
         patches/0014-specialist-autoselect.patch patches/0015-build-info-image.patch \
         .github/workflows/patches.yml docker/Dockerfile; do
  if [[ ! -f "$f" ]]; then
    echo "нет файла: $f" >&2
    missing=1
  fi
done
[[ $missing -eq 0 ]] || exit 1

# Секреты в репозитории: проверка, которая умеет падать.
if command -v grep >/dev/null; then
  leaks=$(grep -RInE 'sk-[A-Za-z0-9]{20}|api[_-]?key[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9]{16}' \
    --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=upstream --exclude-dir=.next \
    --exclude-dir=data . 2>/dev/null || true)
  if [[ -n "$leaks" ]]; then
    echo "похоже на секрет в репозитории:" >&2
    echo "$leaks" >&2
    exit 1
  fi
fi

bash scripts/test-scripts.sh

# CI-файл: валиден как YAML и содержит шаги, без которых проверка бессмысленна.
if command -v python3 >/dev/null && python3 -c 'import yaml' 2>/dev/null; then
  python3 scripts/check-workflow.py
else
  echo "CI-файл: PyYAML нет — проверка YAML пропущена" >&2
fi

# TOUCHED.md: каждый файл, который трогает патч, перечислен в таблице.
python3 scripts/check-touched.py --self-test >/dev/null
python3 scripts/check-touched.py

# Русская локаль: самопроверка валидатора всегда, полная сверка — когда есть checkout upstream.
python3 scripts/check-i18n.py --self-test >/dev/null
if [[ -f upstream/src/i18n/messages.ru.ts ]]; then
  python3 scripts/check-i18n.py
else
  echo "русская локаль: полная сверка пропущена (нет upstream/src/i18n) — самопроверка валидатора прогнана"
fi

# Async-картинки: тест лежит в патче, запускается без зависимостей.
if [[ -f upstream/scripts/test-image-async.ts && -f upstream/src/lib/pi/image-tasks.ts ]] && command -v node >/dev/null; then
  if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
      --import ./upstream/scripts/alias-loader-register.mjs upstream/scripts/test-image-async.ts >/dev/null; then
    echo "async-картинки: тест упал" >&2
    exit 1
  fi
  echo "async-картинки: ok"
else
  echo "async-картинки: тест пропущен (нет патча в upstream/)" >&2
fi

# Скриптовые расписания: тесты лежат в патче, зависимостей не требуют.
if [[ -f upstream/scripts/test-script-schedules.ts ]] && command -v node >/dev/null; then
  for t in test-script-schedules test-script-runner; do
    if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
        --import ./upstream/scripts/alias-loader-register.mjs "upstream/scripts/$t.ts" >/dev/null; then
      echo "скриптовые расписания: тест $t упал" >&2
      exit 1
    fi
  done
  echo "скриптовые расписания: ok"
else
  echo "скриптовые расписания: тесты пропущены (нет патча в upstream/)" >&2
fi

# Расход по чату: тест лежит в патче.
if [[ -f upstream/scripts/test-usage-summary.ts ]] && command -v node >/dev/null; then
  if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
      --import ./upstream/scripts/alias-loader-register.mjs upstream/scripts/test-usage-summary.ts >/dev/null; then
    echo "расход по чату: тест упал" >&2
    exit 1
  fi
  echo "расход по чату: ok"
else
  echo "расход по чату: тест пропущен (нет патча в upstream/)" >&2
fi

# Расход по проекту: тест лежит в патче.
if [[ -f upstream/scripts/test-project-usage.ts ]] && command -v node >/dev/null; then
  if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
      --import ./upstream/scripts/alias-loader-register.mjs upstream/scripts/test-project-usage.ts >/dev/null; then
    echo "расход по проекту: тест упал" >&2
    exit 1
  fi
  echo "расход по проекту: ok"
else
  echo "расход по проекту: тест пропущен (нет патча в upstream/)" >&2
fi

# Сборка: тест версии лежит в патче.
if [[ -f upstream/scripts/test-build-info.ts ]] && command -v node >/dev/null; then
  if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
      --import ./upstream/scripts/alias-loader-register.mjs upstream/scripts/test-build-info.ts >/dev/null; then
    echo "номер сборки: тест упал" >&2
    exit 1
  fi
  echo "номер сборки: ok"
else
  echo "номер сборки: тест пропущен (нет патча в upstream/)" >&2
fi

# Специалист чата: правила выбора лежат в патче, сети не требуют.
if [[ -f upstream/scripts/test-specialist-choice.ts ]] && command -v node >/dev/null; then
  if ! node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON --experimental-strip-types \
      --import ./upstream/scripts/alias-loader-register.mjs upstream/scripts/test-specialist-choice.ts >/dev/null; then
    echo "специалист чата: тест упал" >&2
    exit 1
  fi
  echo "специалист чата: ok"
else
  echo "специалист чата: тест пропущен (нет патча в upstream/)" >&2
fi

# Типизированная память: формат и негативные кейсы скрипта.
python3 scripts/memory.py --self-test >/dev/null
for memory_file in templates/*/project/memory.md; do
  [ -f "$memory_file" ] || continue
  python3 scripts/memory.py check "$memory_file" >/dev/null || { echo "память шаблона: формат нарушен: $memory_file" >&2; exit 1; }
done
echo "типизированная память: ok"

# Шаблоны проектов: формат, установка в пустой каталог, проверка и её падения.
python3 scripts/check-templates.py --self-test >/dev/null
python3 scripts/check-templates.py

# Личные данные: репозиторий публичный, здесь только плейсхолдеры (решение 41).
python3 scripts/check-private.py --self-test >/dev/null
python3 scripts/check-private.py

# Каталог специалистов: пакеты в bundled-skills/ по контракту каталога Eggent.
python3 scripts/check-specialists.py --self-test >/dev/null
python3 scripts/check-specialists.py

# Внешние источники: сайт и Яндекс — тесты на подставном HTTP, без сети и без токенов.
if [[ -f skills/external-sources/site_audit.py ]]; then
  if ! ( cd skills/external-sources && python3 -m unittest discover -s tests >/dev/null 2>&1 ); then
    echo "внешние источники: тесты упали (cd skills/external-sources && python3 -m unittest discover -s tests)" >&2
    exit 1
  fi
  echo "внешние источники: ok"
fi

# Адаптер почты: тесты на stdlib, без сети и без зависимостей.
if [[ -f mail-adapter/adapter/api.py ]]; then
  if ! ( cd mail-adapter && python3 -m unittest discover -s tests -t . >/dev/null 2>&1 ); then
    echo "адаптер почты: тесты упали (cd mail-adapter && python3 -m unittest discover -s tests -t .)" >&2
    exit 1
  fi
  echo "адаптер почты: ok"
fi

# Словарь намерений: тест upstream, если рядом есть его checkout с package.json.
if [[ -f upstream/package.json && -f upstream/scripts/test-vocabulary.ts ]]; then
  if ! ( cd upstream && npm run -s test:vocabulary ); then
    echo "словарь намерений: тест upstream упал" >&2
    exit 1
  fi
else
  echo "словарь намерений: тест upstream пропущен (нет полного checkout в upstream/)"
fi

echo "eggent-plus: проверки пройдены"
