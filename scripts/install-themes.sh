#!/usr/bin/env bash
# Ставит темы в данные экземпляра и, если попросили, включает одну.
#
#   ./scripts/install-themes.sh /app/data              # положить три темы рядом
#   ./scripts/install-themes.sh /app/data warm         # и включить «warm»
#   ./scripts/install-themes.sh /app/data --off        # выключить тему
#
# Тема — файл CSS с переменными в data/themes/current.css. Включить = скопировать
# файл под этим именем; выключить = удалить его. Ничего не перезаписывается молча:
# если current.css уже есть и это не наша тема, скрипт откажется, пока не скажут --force.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

data="${1:-/app/data}"
choice="${2:-}"
themes="$data/themes"

[ -d "$data" ] || { echo "нет каталога данных: $data" >&2; exit 2; }
mkdir -p "$themes"

if [[ "$choice" == "--off" ]]; then
  rm -f "$themes/current.css" && echo "тема выключена"
  exit 0
fi

for theme in docker/themes/*.css; do
  cp "$theme" "$themes/$(basename "$theme")"
done
echo "в data/themes: $(ls "$themes"/*.css 2>/dev/null | wc -l) файлов"

[[ -z "$choice" ]] && exit 0

source_file="$themes/$choice.css"
[ -f "$source_file" ] || { echo "нет темы $choice (есть: $(cd "$themes" && ls *.css 2>/dev/null | sed 's/\.css$//' | tr '\n' ' '))" >&2; exit 1; }

if [[ -f "$themes/current.css" ]] && ! cmp -s "$source_file" "$themes/current.css"; then
  if [[ "${3:-}" != "--force" ]]; then
    echo "current.css уже есть и это другая тема — скажи --force, чтобы заменить" >&2
    exit 1
  fi
fi
cp "$source_file" "$themes/current.css"
echo "включена тема $choice"
