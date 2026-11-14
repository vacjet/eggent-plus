# Вынести адаптер туда, куда агент не достаёт

Зачем: подтверждение отправки защищает от модели, которая читает только свой воркспейс. Если же
агенту доступен шелл на машине с адаптером, он прочитает и секрет ящика, и код — то есть обойдёт
подтверждение. Настоящая граница — отдельная машина: там адаптер и ящик, а в Eggent остаются только
адрес и токен.

## Порядок

1. LXC `eggent-mail` (Debian 13, 1 ядро, 512 МБ, 4 ГБ), python3, без доступа к нему из контейнера
   Eggent, кроме порта адаптера. SSH-ключ есть только у владельца, не у агента.
2. На нём:

```bash
useradd --system --home /var/lib/eggent-mail --shell /usr/sbin/nologin eggent-mail
install -d -o eggent-mail -g eggent-mail -m 700 /var/lib/eggent-mail /var/lib/eggent-mail/secrets
install -d -m 755 /opt/eggent-mail-adapter /etc/eggent-mail
# код адаптера — из репозитория (mail-adapter/adapter, README.md)
cp -r adapter /opt/eggent-mail-adapter/
install -m 600 /dev/null /etc/eggent-mail/adapter.env   # EGGENT_MAIL_ADAPTER_TOKEN, EGGENT_EMAIL_ADDRESS
install -m 600 /dev/null /var/lib/eggent-mail/secrets/work  # пароль приложения
cp systemd/eggent-mail-adapter.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now eggent-mail-adapter
```

3. В Eggent остаются только три значения: `EGGENT_EMAIL_API_URL=http://<lxc>:8787`,
   `EGGENT_SERVICES_TOKEN=<токен>`, `EGGENT_EMAIL_ADDRESS=<адрес>`. Секрета ящика там нет.

## Проверка границы

С машины, где работает агент, должно быть недоступно:

```bash
ssh root@<lxc> cat /var/lib/eggent-mail/secrets/work   # должно отказать
ls /var/lib/eggent-mail                                # каталога нет
```

Если это выполняется — граница не построена, адаптер всё ещё рядом с агентом.

Важно: контейнер на том же Proxmox, где у агента есть root, границей не является — `pct exec <id>`
читает файл секрета в обход SSH. Изоляция закрывается только тогда, когда у агента нет и доступа
к гипервизору: ключ из `/root/.ssh/authorized_keys` на Proxmox удаляется (или выдаётся отдельный
пользователь без прав на `pct`).
