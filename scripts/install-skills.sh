#!/usr/bin/env bash
# Установка скилла `external-sources` в экземпляр Eggent: копия в skills проекта.
#
#   ./scripts/install-skills.sh /root/eggent-plus/testdata-ru [id-проекта]
#
# Без id берётся первый проект в data/projects. Скилл — это контент, поэтому он живёт
# в данных экземпляра, а не в патче ядра: обновление образа его не затирает.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "использование: $0 <каталог data экземпляра> [id проекта]" >&2
  exit 2
fi

DATA_DIR=${1%/}
PROJECT_ID=${2:-}
SKILL_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../skills/external-sources" && pwd)"

if [[ ! -d "$DATA_DIR/projects" ]]; then
  echo "нет каталога проектов: $DATA_DIR/projects" >&2
  exit 1
fi

if [[ -z "$PROJECT_ID" ]]; then
  PROJECT_ID=$(find "$DATA_DIR/projects" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | head -n 1)
fi
if [[ -z "$PROJECT_ID" || ! -d "$DATA_DIR/projects/$PROJECT_ID" ]]; then
  echo "проект не найден: ${PROJECT_ID:-<пусто>}" >&2
  exit 1
fi

TARGET="$DATA_DIR/projects/$PROJECT_ID/skills/external-sources"
mkdir -p "$TARGET/tests"
for name in SKILL.md common.py site_audit.py yandex_read.py; do
  install -m 644 "$SKILL_SRC/$name" "$TARGET/$name"
done
for source in "$SKILL_SRC"/tests/*.py; do
  install -m 644 "$source" "$TARGET/tests/$(basename "$source")"
done

# Проверка, которая умеет падать: скилл без frontmatter и скрипт без статуса не считаются установленными.
grep -q '^name: external-sources$' "$TARGET/SKILL.md" || {
  echo "SKILL.md без строки 'name: external-sources'" >&2
  exit 1
}
grep -q '^description: ' "$TARGET/SKILL.md" || {
  echo "SKILL.md без description" >&2
  exit 1
}
PYTHONDONTWRITEBYTECODE=1 python3 "$TARGET/site_audit.py" --status --out "$DATA_DIR/external" >/dev/null || {
  echo "site_audit.py не отвечает на --status" >&2
  exit 1
}

echo "скилл установлен: $TARGET"
echo "данные будут в $DATA_DIR/external; расписание — $DATA_DIR/scripts/schedules.json"
