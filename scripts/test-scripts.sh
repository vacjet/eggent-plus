#!/usr/bin/env bash
# Проверки скриптов eggent-plus. Каждая проверка с отрицательным случаем:
# успех теста = запрещённое действие не сработало.
#
#   ./scripts/test-scripts.sh
#
# Выход 0 — все проверки прошли; 1 — есть провал (имя проверки в stderr).
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fails=0
pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; fails=$((fails + 1)); }

# ---------- apply-patches ----------
new_repo() {
  local d="$1"
  rm -rf "$d"; mkdir -p "$d/scripts" "$d/patches"
  cp "$here/scripts/apply-patches.sh" "$d/scripts/"
  ( cd "$d" && git init -q . \
    && printf 'one\ntwo\n' > a.txt \
    && git add a.txt \
    && git -c user.email=t@t -c user.name=t commit -qm init )
}

echo "apply-patches:"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT

# 1. Хороший патч применяется.
repo="$work/good"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nthree\n' > a.txt && git diff > patches/0001-good.patch && git checkout -q a.txt )
if ( cd "$repo" && bash scripts/apply-patches.sh >/dev/null 2>&1 ) && grep -qx three "$repo/a.txt"; then
  pass "хороший патч применён"
else
  fail "хороший патч не применился"
fi

# 2. Битый патч должен упасть с кодом 1.
repo="$work/broken"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nfour\n' > a.txt && git diff > patches/0001-good.patch && git checkout -q a.txt
  printf 'diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n-nope\n-nope\n+yes\n+yes\n' > patches/0002-broken.patch )
( cd "$repo" && bash scripts/apply-patches.sh >/dev/null 2>&1 ); code=$?
if [[ $code -eq 1 ]]; then pass "битый патч отклонён (код 1)"; else fail "битый патч не отклонён (код $code)"; fi

# 3. Пустой каталог патчей — код 2.
repo="$work/empty"; new_repo "$repo"
( cd "$repo" && bash scripts/apply-patches.sh >/dev/null 2>&1 ); code=$?
if [[ $code -eq 2 ]]; then pass "нет патчей — код 2"; else fail "нет патчей — код $code, ждали 2"; fi

# 4. --check на хорошем патче: код 0 и файл не изменён.
repo="$work/checkok"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nthree\n' > a.txt && git diff > patches/0001-good.patch && git checkout -q a.txt )
if ( cd "$repo" && bash scripts/apply-patches.sh --check >/dev/null 2>&1 ) && ! grep -qx three "$repo/a.txt"; then
  pass "--check на хорошем патче прошёл, файл цел"
else
  fail "--check на хорошем патче: код или файл не те"
fi

# 5. --check на испорченной строке контекста — код 1.
repo="$work/checkbad"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nthree\n' > a.txt && git diff > patches/0001-good.patch && git checkout -q a.txt
  sed -i 's/^ one$/ oneoops/' patches/0001-good.patch )
( cd "$repo" && bash scripts/apply-patches.sh --check >/dev/null 2>&1 ); code=$?
if [[ $code -eq 1 ]]; then pass "--check отклонил патч с битым контекстом (код 1)"; else fail "битый контекст не отклонён (код $code)"; fi

# 6. Checkout в подкаталоге upstream/: патч применяется туда, корень сборки не тронут.
repo="$work/subdir"; rm -rf "$repo"; mkdir -p "$repo/scripts" "$repo/patches" "$repo/upstream"
cp "$here/scripts/apply-patches.sh" "$repo/scripts/"
( cd "$repo/upstream" && git init -q . && printf 'one\ntwo\n' > a.txt && git add a.txt \
  && git -c user.email=t@t -c user.name=t commit -qm init \
  && printf 'one\ntwo\nthree\n' > a.txt && git diff > "$repo/patches/0001-sub.patch" && git checkout -q a.txt )
if ( cd "$repo" && bash scripts/apply-patches.sh >/dev/null 2>&1 ) && grep -qx three "$repo/upstream/a.txt" \
   && [[ ! -e "$repo/a.txt" ]]; then
  pass "патч применён в checkout upstream/, корень сборки цел"
else
  fail "патч не попал в checkout upstream/"
fi

# 7. Второй патч опирается на первый: --check проверяет набор по очереди и проходит.
repo="$work/chain"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nthree\n' > a.txt && git diff > patches/0001-first.patch && git checkout -q a.txt
  printf 'diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n two\n-three\n+four\n' > patches/0002-second.patch )
if ( cd "$repo" && bash scripts/apply-patches.sh --check >/dev/null 2>&1 ); then
  pass "--check принимает патч, который опирается на предыдущий"
else
  fail "--check отверг зависимый патч — второй патч не увидел результат первого"
fi

# 8. Второй патч ломает набор — код 1 и файл не изменён.
repo="$work/chainbad"; new_repo "$repo"
( cd "$repo" && printf 'one\ntwo\nthree\n' > a.txt && git diff > patches/0001-first.patch && git checkout -q a.txt
  printf 'diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1,3 +1,3 @@\n one\n two\n-nope\n+four\n' > patches/0002-second.patch )
( cd "$repo" && bash scripts/apply-patches.sh --check >/dev/null 2>&1 ); code=$?
if [[ $code -eq 1 ]] && grep -qx two "$repo/a.txt"; then
  pass "битый второй патч в наборе отклонён (код 1)"
else
  fail "битый набор не отклонён или файл изменён (код $code)"
fi

# ---------- backup / restore ----------
echo "backup/restore:"
src="$work/data"; mkdir -p "$src/projects/p1"
printf 'важные данные\n' > "$src/projects/p1/context.md"
out="$work/backup"

if bash "$here/scripts/backup.sh" "$src" "$out" >/dev/null 2>&1; then
  archive="$(ls "$out"/eggent-data-*.tar.gz | head -1)"
  pass "копия создана"
else
  fail "backup не сработал"; archive=""
fi

if [[ -n "$archive" ]]; then
  dst="$work/restored"
  if bash "$here/scripts/restore.sh" "$archive" "$dst" >/dev/null 2>&1 \
     && grep -qx 'важные данные' "$dst/data/projects/p1/context.md"; then
    pass "восстановление вернуло файл"
  else
    fail "восстановление не вернуло файл"
  fi

  # 7. Испорченная копия должна быть отклонена.
  bad="$work/badcopy.tar.gz"; cp "$archive" "$bad"; printf 'x' >> "$bad"
  cp "$archive.sha256" "$bad.sha256" 2>/dev/null || true
  sed -i "s/$(basename "$archive")/$(basename "$bad")/" "$bad.sha256" 2>/dev/null || true
  bash "$here/scripts/restore.sh" "$bad" "$work/restored-bad" >/dev/null 2>&1; code=$?
  if [[ $code -eq 1 ]]; then pass "испорченная копия отклонена (код 1)"; else fail "испорченная копия принята (код $code)"; fi

  # 8. Непустой каталог назначения — отказ.
  bash "$here/scripts/restore.sh" "$archive" "$work/restored" >/dev/null 2>&1; code=$?
  if [[ $code -eq 1 ]]; then pass "непустой каталог отклонён (код 1)"; else fail "непустой каталог принят (код $code)"; fi
fi

echo
if [[ $fails -eq 0 ]]; then
  echo "все проверки прошли"
  exit 0
fi
echo "провалов: $fails" >&2
exit 1
