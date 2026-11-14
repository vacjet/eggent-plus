# Затронутые файлы ядра

Здесь перечислено всё, что патчи eggent-plus меняют в исходниках upstream. Чем короче список, тем
дешевле обновления: перед каждым новым тегом Eggent сначала смотрим сюда, потом на CI.

| Файл upstream | Зачем | Патч |
|---|---|---|
| `src/i18n/locales.ts` | добавить `ru` в `SUPPORTED_LOCALES` | ru-locale |
| `src/i18n/messages.ru.ts` | новый файл перевода (1773 ключа, включая строки расхода) | ru-locale, chat-usage, project-usage, build-version, specialist-autoselect, card-proof, file-review, command-policy |
| `src/i18n/messages.ts` | регистрация русского словаря (`ru: ruMessages`), ключи подписи расхода, специалиста, карточки, правок файлов и политики команд | ru-locale, chat-usage, specialist-autoselect, card-proof, file-review, command-policy |
| `src/i18n/vocabulary.ts` | русские намерения и стоп-слова | ru-locale |
| `src/lib/pi/eggent-tools.ts` | асинхронные картинки (задача → опрос → файл); инструмент `eggent_script_schedules` | image-async, script-schedules |
| `src/lib/pi/image-tasks.ts` | новый файл: распознать задачу в ответе провайдера и дождаться картинки | image-async |
| `scripts/test-image-async.ts` | новый файл: проверки опроса задачи без сети | image-async |
| `src/lib/pi/usage-summary.ts` | новый файл: сумма токенов по всему чату из статистики ответов | chat-usage |
| `src/lib/types.ts` | поле мягкого порога в настройках (`general.usageSoftLimitTokens`), специалист на чате | soft-limit, specialist-autoselect |
| `src/lib/storage/settings-store.ts` | значение по умолчанию для порога (0 = выключено) | soft-limit |
| `src/app/api/chat/history/route.ts` | порог приходит вместе с чатом, без второго запроса | soft-limit |
| `src/lib/build-info.ts` | какой сборка отвечает (тег, число патчей, коммит); образ главнее данных | build-version, build-info-image |
| `src/app/api/build-info/route.ts` | новый маршрут: отдаёт `data/build-info.json` странице настроек | build-version |
| `src/app/dashboard/settings/general/page.tsx` | строка «Сборка …» и поле мягкого порога в «Общих» настройках | build-version, soft-limit |
| `scripts/test-build-info.ts` | проверки версии сборки (9 кейсов: строка, чтение, образ против данных) | build-version, build-info-image |
| `src/lib/usage/project-usage.ts` | новый файл: сумма по чатам проекта | project-usage |
| `src/app/api/projects/[id]/usage/route.ts` | новый маршрут: расход проекта для настроек проекта | project-usage |
| `src/components/project-model-settings.tsx` | строка «этот проект потратил N токенов» | project-usage |
| `scripts/test-project-usage.ts` | новый файл: проверки суммы по проекту (9 кейсов) | project-usage |
| `src/components/chat/chat-input.tsx` | подпись «за чат N», предупреждающий цвет за порогом | chat-usage, soft-limit |
| `src/components/chat/chat-panel.tsx` | сумма по чату из частей ответа; порог из настроек; чтение и переключение специалиста | chat-usage, soft-limit, specialist-autoselect |
| `scripts/test-usage-summary.ts` | новый файл: проверки суммы (8 кейсов) | chat-usage |
| `src/lib/scripts/schedules.ts` | новый файл: что значит расписание, когда наступает, когда пора запускать | script-schedules |
| `src/lib/scripts/runner.ts` | новый файл: запуск команды, журнал запусков, тик и хранилище | script-schedules |
| `src/instrumentation.node.ts` | старт цикла скриптовых расписаний вместе с остальными службами | script-schedules |
| `scripts/test-script-schedules.ts`, `scripts/test-script-runner.ts` | новые файлы: проверки расписаний и запуска (20 + 17 кейсов) | script-schedules |
| `src/lib/email/config.ts`, `src/lib/email/sync.ts` | режим `imap` рядом с облачным | imap-mail |
| `src/components/files/version-diff.tsx`, `version-history.tsx` | «принять / отклонить» правку | accept-reject |
| `src/lib/board/types.ts` | поле `proof` на карточке: чем закрыта | card-proof |
| `src/lib/board/store.ts` | чтение `proof` при загрузке карточки | card-proof |
| `src/lib/board/cards.ts` | в `done` — только с «чем проверено»; новый запуск стирает старое | card-proof |
| `src/app/api/board/cards/[id]/route.ts` | `move.proof` в PATCH карточки | card-proof |
| `src/lib/board/client.ts` | `moveCard(..., proof)` | card-proof |
| `src/components/board/card-sheet.tsx` | поле «Чем проверено?» перед закрытием карточки | card-proof |
| `src/lib/files/versions/review.ts` | новый файл: какая правка агента предлагается к отмене и сам откат | file-review |
| `src/app/api/files/versions/review/route.ts` | новый маршрут: чтение правок к отмене и решение «принять / отклонить» | file-review |
| `src/components/chat/files-produced.tsx` | строка «правка агента» с «Отклонить» и «Оставить» под ответом | file-review |
| `scripts/test-file-review.ts` | новый файл: 7 кейсов выбора версии для отмены | file-review |
| `src/lib/pi/command-policy.ts` | новый файл: правила deny/ask/allow для команд оболочки и исключения из политики | command-policy |
| `src/lib/pi/interactive-bash-tool.ts` | проверка команды до запуска: отказ, вопрос человеку, запуск | command-policy |
| `scripts/test-command-policy.ts` | новый файл: 25 кейсов правил и исключений | command-policy |
| `src/lib/themes/current.ts` | новый файл: тема как файл `data/themes/current.css` и проверка, что это CSS | theme-file |
| `src/app/api/theme.css/route.ts` | новый маршрут: отдаёт тему странице | theme-file |
| `src/app/layout.tsx` | ссылка на тему в `<head>`, когда файл есть | theme-file |
| `scripts/test-theme-file.ts` | новый файл: 6 кейсов «что считается темой» | theme-file |
| `src/lib/specialists/choice.ts` | новый файл: правила выбора специалиста, промпт, разбор ответа модели | specialist-autoselect |
| `src/lib/specialists/catalog.ts` | новый файл: специалисты, установленные в проекте (`specialist.json` рядом со скиллом) | specialist-autoselect |
| `src/lib/specialists/select.ts` | новый файл: один вызов модели без инструментов, таймаут, выбор модели | specialist-autoselect |
| `src/lib/specialists/assign.ts` | новый файл: каталог → выбор → сохранение в чат | specialist-autoselect |
| `src/app/api/chat/[chatId]/specialist/route.ts` | новый маршрут: чтение и переключение специалиста чата | specialist-autoselect |
| `src/components/chat/specialist-badge.tsx` | новый компонент: бейдж специалиста с меню | specialist-autoselect |
| `src/components/chat/chat-specialist-slot.tsx` | новый компонент: передача бейджа из чата в шапку | specialist-autoselect |
| `scripts/test-specialist-choice.ts` | новый файл: проверки правил выбора (19 кейсов, без сети) | specialist-autoselect |
| `src/components/site-header.tsx` | слот для элементов экрана рядом с заголовком | specialist-autoselect |
| `src/app/dashboard/(chat)/layout.tsx` | провайдер и бейдж в шапке экрана чата | specialist-autoselect |
| `src/app/api/chat/route.ts` | автовыбор специалиста до начала хода | specialist-autoselect |
| `src/lib/pi/types.ts` | опция хода: с каким специалистом чат | specialist-autoselect |
| `src/lib/pi/chat-runner.ts` | заметка ходу о специалисте и его скилле | specialist-autoselect |
| `src/lib/storage/chat-store.ts` | `setChatSpecialist` — выбор или снятие специалиста | specialist-autoselect |
| `Dockerfile` | `build-info.json` пишется в образ из build-arg (тег, число патчей, коммит) | build-info-image |

Правило: новый патч добавляет строку в эту таблицу. Закрытые апстримом пункты (лимит вложений —
уже 100 МБ, RAG/`kb_search` — удалён в 0.8.0) из таблицы убраны, см. `docs/stage-1-recheck.md`. Если патч трогает файл вне таблицы — это повод
пересмотреть, нельзя ли сделать то же скиллом или конфигом.
