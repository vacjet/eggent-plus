# Затронутые файлы ядра

Здесь перечислено всё, что патчи eggent-plus меняют в исходниках upstream. Чем короче список, тем
дешевле обновления: перед каждым новым тегом Eggent сначала смотрим сюда, потом на CI.

| Файл upstream | Зачем | Патч |
|---|---|---|
| `src/i18n/locales.ts` | добавить `ru` в `SUPPORTED_LOCALES` | ru-locale |
| `src/i18n/messages.ru.ts` | новый файл перевода (1773 ключа, включая строки расхода) | ru-locale, chat-usage, project-usage, build-version |
| `src/i18n/messages.ts` | регистрация русского словаря (`ru: ruMessages`) и два ключа подписи расхода по чату | ru-locale, chat-usage |
| `src/i18n/vocabulary.ts` | русские намерения и стоп-слова | ru-locale |
| `src/lib/pi/eggent-tools.ts` | асинхронные картинки (задача → опрос → файл); инструмент `eggent_script_schedules` | image-async, script-schedules |
| `src/lib/pi/image-tasks.ts` | новый файл: распознать задачу в ответе провайдера и дождаться картинки | image-async |
| `scripts/test-image-async.ts` | новый файл: проверки опроса задачи без сети | image-async |
| `src/lib/pi/usage-summary.ts` | новый файл: сумма токенов по всему чату из статистики ответов | chat-usage |
| `src/lib/types.ts` | поле мягкого порога в настройках (`general.usageSoftLimitTokens`) | soft-limit |
| `src/lib/storage/settings-store.ts` | значение по умолчанию для порога (0 = выключено) | soft-limit |
| `src/app/api/chat/history/route.ts` | порог приходит вместе с чатом, без второго запроса | soft-limit |
| `src/lib/build-info.ts` | новый файл: какая сборка отвечает (тег, число патчей, коммит) | build-version |
| `src/app/api/build-info/route.ts` | новый маршрут: отдаёт `data/build-info.json` странице настроек | build-version |
| `src/app/dashboard/settings/general/page.tsx` | строка «Сборка …» и поле мягкого порога в «Общих» настройках | build-version, soft-limit |
| `scripts/test-build-info.ts` | новый файл: проверки версии сборки (6 кейсов) | build-version |
| `src/lib/usage/project-usage.ts` | новый файл: сумма по чатам проекта | project-usage |
| `src/app/api/projects/[id]/usage/route.ts` | новый маршрут: расход проекта для настроек проекта | project-usage |
| `src/components/project-model-settings.tsx` | строка «этот проект потратил N токенов» | project-usage |
| `scripts/test-project-usage.ts` | новый файл: проверки суммы по проекту (9 кейсов) | project-usage |
| `src/components/chat/chat-input.tsx` | подпись «за чат N», предупреждающий цвет за порогом | chat-usage, soft-limit |
| `src/components/chat/chat-panel.tsx` | сумма по чату из частей ответа; порог из настроек в поле ввода | chat-usage, soft-limit |
| `scripts/test-usage-summary.ts` | новый файл: проверки суммы (8 кейсов) | chat-usage |
| `src/lib/scripts/schedules.ts` | новый файл: что значит расписание, когда наступает, когда пора запускать | script-schedules |
| `src/lib/scripts/runner.ts` | новый файл: запуск команды, журнал запусков, тик и хранилище | script-schedules |
| `src/instrumentation.node.ts` | старт цикла скриптовых расписаний вместе с остальными службами | script-schedules |
| `scripts/test-script-schedules.ts`, `scripts/test-script-runner.ts` | новые файлы: проверки расписаний и запуска (20 + 17 кейсов) | script-schedules |
| `src/lib/email/config.ts`, `src/lib/email/sync.ts` | режим `imap` рядом с облачным | imap-mail |
| `src/components/files/version-diff.tsx`, `version-history.tsx` | «принять / отклонить» правку | accept-reject |

Правило: новый патч добавляет строку в эту таблицу. Закрытые апстримом пункты (лимит вложений —
уже 100 МБ, RAG/`kb_search` — удалён в 0.8.0) из таблицы убраны, см. `docs/stage-1-recheck.md`. Если патч трогает файл вне таблицы — это повод
пересмотреть, нельзя ли сделать то же скиллом или конфигом.
