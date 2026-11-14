# mail-adapter

Маленький сервис, который даёт self-hosted Eggent **входящие**: читает ящик по IMAP и отвечает
по тому же контракту, что облачный почтовый сервис Eggent Cloud. Ядро при этом не патчится:
достаточно указать ему `EGGENT_EMAIL_API_URL` на этот адаптер, и встроенный инструмент
`eggent_email` (список, чтение, вложения, отправка) работает как в облаке.

## Зачем именно так

В 0.8.0 почта устроена как тонкий HTTP-клиент к сервису (`src/lib/email/client.ts`): письма живут
на сервисе, рабочее пространство опрашивает `GET /messages?after=<id>` и хранит свою копию. IMAP
в ядре нет вообще, а self-hosted умеет только отправлять через SMTP и не имеет входящих. Поэтому
дешевле и честнее подставить сервис, чем патчить ядро и тащить в него зависимости.

Эндпоинты, которые вызывает Eggent:

| Метод | Путь | Что отдаёт |
|---|---|---|
| GET | `/status` | адрес, непрочитанные, ящики |
| GET | `/messages?folder=&after=&unread=1&limit=` | список писем |
| GET | `/messages/<id>` | письмо с текстом |
| POST | `/messages/<id>/read` | отметить прочитанным (в нашей копии) |
| GET | `/messages/<id>/attachments/<n>` | файл вложения |
| POST | `/send` | отправить письмо через SMTP |

Только стандартная библиотека Python 3.11+ (imaplib, smtplib, sqlite3, http.server) — ни одной
внешней зависимости.

## Настройка

1. Включите IMAP в самом ящике и получите **пароль приложения** (у Яндекса: Настройки → Безопасность →
   Пароли приложений; обычный пароль от аккаунта не подойдёт).

2. Конфигурация ящиков — `data/mail/accounts.json`:

```json
{
  "accounts": [
    {
      "id": "work",
      "address": "mail@example.com",
      "name": "Рабочий ящик",
      "owner": "me@example.ru",
      "days": 30,
      "folders": ["INBOX", "Sent"],
      "imap": { "host": "imap.yandex.ru", "port": 993, "tls": true },
      "smtp": { "host": "smtp.yandex.ru", "port": 465, "tls": true }
    }
  ]
}
```

Для `yandex.ru`, `gmail.com`, `mail.ru` хосты подставляются сами — их можно не писать.

3. Пароль — **не в этом файле**. Либо файл `data/mail/secrets/<id>` с правами `600`, либо
   переменная окружения `EGGENT_MAIL_PASSWORD_<ID>`:

```bash
install -m 600 /dev/null data/mail/secrets/work
printf '%s' 'пароль-приложения' > data/mail/secrets/work
```

Адаптер откажется стартовать, если пароль нашёлся в `accounts.json` или файл секрета открыт другим:
лучше громкий отказ на старте, чем тихая утечка в репозиторий.

## Запуск

```bash
cd mail-adapter
export EGGENT_MAIL_DIR=/app/data/mail
export EGGENT_MAIL_ADAPTER_TOKEN="$(openssl rand -hex 24)"   # тот же токен пропишите Eggent
python3 -m adapter
```

Переменные: `EGGENT_MAIL_ACCOUNTS` (путь к accounts.json), `EGGENT_MAIL_DB` (путь к SQLite),
`EGGENT_MAIL_PORT` (по умолчанию 8787), `EGGENT_MAIL_SYNC_SECONDS` (по умолчанию 300).

## Подключение к Eggent

В окружении контейнера Eggent:

```
EGGENT_EMAIL_API_URL=http://<адрес-адаптера>:8787
EGGENT_SERVICES_TOKEN=<EGGENT_MAIL_ADAPTER_TOKEN>
EGGENT_EMAIL_ADDRESS=mail@example.com
```

Если Eggent в Docker, а адаптер на хосте — используйте `--add-host=host.docker.internal:host-gateway`
и адрес `http://host.docker.internal:8787`, либо положите оба в один compose.

Проверка: `curl -H "Authorization: Bearer $EGGENT_MAIL_ADAPTER_TOKEN" http://127.0.0.1:8787/status`
→ `{"enabled": true, ...}`. В Eggent после этого агент видит почту: «что пришло за неделю» отвечает
из `list_emails`.

## Проверки

```bash
cd mail-adapter
python3 -m unittest discover -s tests -t .     # 24 теста: MIME, HTTP-контракт, конфигурация
```

Не проверено живым ящиком: нужен пароль приложения. IMAP- и SMTP-код написан по документированному
протоколу, но первый настоящий прогон должен быть на твоём ящике, только на чтение.

## Чего здесь нет и почему

- **Экрана почты.** В Eggent Cloud его тоже нет: письма читает агент через `eggent_email`. Список
  сообщений компании (`/dashboard/messages`) — другая подсистема, не почта.
- **Отметки `\Seen` в ящике.** Отметка прочтения живёт в нашей копии: чужой ящик не меняем.
- **Тредов, папок как в клиенте, поиска по всему ящику.** Это почтовый клиент, он за границей проекта.
