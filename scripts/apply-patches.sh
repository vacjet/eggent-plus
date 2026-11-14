#!/usr/bin/env bash
# eggent-plus: накладывает patches/*.patch по порядку имён на checkout upstream.
#
#   ./scripts/apply-patches.sh          применить
#   ./scripts/apply-patches.sh --check  только проверить, что накладываются
#
# Checkout выбирается так: $EGGENT_UPSTREAM, иначе ./upstream (если это git-репозиторий),
# иначе сам каталог репозитория (удобно для тестов и для checkout на месте).
#
# Выход: 0 — все патчи легли; 1 — первый патч не лёг (имя в stderr); 2 — нет checkout/патчей.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${EGGENT_UPSTREAM:-}" ]]; then
  target="$EGGENT_UPSTREAM"
elif [[ -d "$root/upstream/.git" ]]; then
  target="$root/upstream"
else
  target="$root"
fi
if [[ ! -d "$target/.git" ]]; then
  echo "не git-репозиторий: $target" >&2
  exit 2
fi
target="$(cd "$target" && pwd)"
cd "$root"

mode="${1:-apply}"
case "$mode" in
  apply | --check) ;;
  *) echo "usage: $0 [--check]" >&2; exit 2 ;;
esac

shopt -s nullglob
patches=(patches/*.patch)
if [[ ${#patches[@]} -eq 0 ]]; then
  echo "patches/: файлов .patch нет" >&2
  exit 2
fi

# --check проверяет набор целиком: один вызов git apply читает все диффы по очереди, поэтому патч,
# который опирается на предыдущий, виден как накладывающийся. Проверка по одному дала бы ложный
# провал у второго патча — он ожидает результат первого.
if [[ "$mode" == "--check" ]]; then
  combined="$(mktemp)"
  trap 'rm -f "$combined"' EXIT
  cat "${patches[@]}" > "$combined"
  if ! git -C "$target" apply --check "$combined" 2>/tmp/apply-check-error.$$; then
    echo "FAILED check: набор патчей не ложится на $target" >&2
    sed 's/^/  /' "/tmp/apply-check-error.$$" >&2
    rm -f "/tmp/apply-check-error.$$"
    # Назвать виновного: по одному, в порядке имён.
    for p in "${patches[@]}"; do
      git -C "$target" apply --check "$root/$p" 2>/dev/null \
        && echo "  отдельно ложится: $p" \
        || echo "  отдельно НЕ ложится: $p" >&2
    done
    exit 1
  fi
  rm -f "/tmp/apply-check-error.$$"
  for p in "${patches[@]}"; do echo "ok (check): $p"; done
  exit 0
fi

for p in "${patches[@]}"; do
  # Патч задан путём от корня репозитория сборки, применяется в checkout upstream.
  if ! git -C "$target" apply "$root/$p"; then
    echo "FAILED apply: $p (checkout: $target)" >&2
    exit 1
  fi
  echo "ok (apply): $p"
done
