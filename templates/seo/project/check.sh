#!/usr/bin/env bash
# Проверка проекта: структура на месте, отчёты названы по дате, в файлах нет токенов.
#
# Запускается из корня проекта: ./check.sh
# Коды: 0 — всё сходится, 1 — есть нарушение (что именно — в stderr).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

fail() { echo "FAIL: $*" >&2; exit 1; }

# 1. Структура: без этих папок проект — просто набор файлов.
for dir in data/external reports notes; do
  [ -d "$dir" ] || fail "нет папки $dir"
done

# 2. Секреты не должны попадать в проект: токены живут в окружении экземпляра.
leaks=$(grep -RInE 'YANDEX_SEO_TOKEN[[:space:]]*=[[:space:]]*[A-Za-z0-9_-]{8,}|sk-[A-Za-z0-9]{20}' \
  --exclude-dir=.git --exclude-dir=node_modules . 2>/dev/null || true)
[ -z "$leaks" ] || fail "похоже на токен в проекте:
$leaks"

# 3. Отчёты: имя начинается с даты, иначе их не отсортировать и не найти.
shopt -s nullglob
reports=(reports/*.md)
for report in "${reports[@]}"; do
  base=$(basename "$report")
  [[ "$base" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-.+\.md$ ]] || fail "отчёт без даты в имени: $report"
done

# 4. Отчёт без данных — это мнение. Если отчёт есть, он ссылается на срез в data/external.
for report in "${reports[@]}"; do
  refs=$(grep -oE 'data/external/[A-Za-z0-9._/-]+' "$report" 2>/dev/null | sort -u || true)
  [ -n "$refs" ] || fail "в отчёте нет ссылки на срез данных: $report"
  while IFS= read -r ref; do
    [ -f "$ref" ] || fail "отчёт ссылается на отсутствующий срез: $ref (из $report)"
  done <<< "$refs"
done

echo "ok: структура на месте, отчётов ${#reports[@]}, токенов нет"
