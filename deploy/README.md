# Размещение Platerra

Исходники сайта: `website/`. Архивные `site/` и `recovered/` не публикуются.
Сайт работает отдельным контейнером без открытых наружу портов. Входящий nginx
L4Desk маршрутизирует `platerra.ru` и `www.platerra.ru` через общую Docker-сеть.
Его исходная конфигурация сохранена в `edge/nginx.conf` с одним дополнительным
include; остальные виртуальные хосты и contact relay остаются прежними.

## Первое размещение

1. Собрать и проверить `website/`; доставить исходники в `/home/user1/platerra.ru`.
2. Извлечь из локального `.env` fullchain и соответствующий private key в
   `deploy/tls/`. Проверить домены, срок, совпадение ключа. Доставить по SSH;
   права каталога 700, файлов 600. TLS-материалы никогда не добавлять в Git.
3. Собрать и запустить `docker compose -f deploy/compose.yml up -d --build`.
4. До переключения входящего nginx проверить backend healthz и выполнить
   `nginx -t` с новой конфигурацией. Сохранить исходный inspect контейнера,
   конфигурацию и rollback-инструкцию в защищённой папке на сервере.
5. Пересоздать только landing, используя оба compose-файла:

```sh
export PLATERRA_ROOT=/home/user1/platerra.ru
sudo --preserve-env=PLATERRA_ROOT docker compose \
  -f /home/user1/l4desk-landing/docker-compose.yml \
  -f "$PLATERRA_ROOT/deploy/edge/compose.override.yml" \
  up -d --no-deps --no-build landing
```

6. Проверить HTTPS через `curl --resolve`, все страницы, статические ассеты,
   редиректы, 404 и сохранение работоспособности L4Desk.

При будущих обновлениях L4Desk использовать этот override вместе с его базовым
compose-файлом. После изменения исходной конфигурации L4Desk переносить изменения
в `edge/nginx.conf` и выполнять `nginx -t` перед перезапуском.

## Сертификат

Импортированный сертификат обслуживает сайт сразу. Для автоматического
выпуска/продления используется certbot внутри существующего входящего контейнера,
его сохраняемые ACME-account/config и webroot. Для Platerra HTTP challenge
обслуживается отдельным виртуальным хостом и не перенаправляется на HTTPS.

Локальный `deploy/server.env` на сервере:

```dotenv
PLATERRA_ROOT=/home/user1/platerra.ru
TARGET_IPV4=<IPv4 сервера>
EDGE_CONTAINER=l4desk-landing
```

Установить service/timer из этого каталога в `/etc/systemd/system`, выполнить
`systemctl daemon-reload` и `systemctl enable --now platerra-certificate.timer`.
Скрипт откладывает обращение к LE, пока DNS обоих имён не указывает только
на целевой IPv4. Затем certbot выпускает управляемый сертификат, а скрипт
проверяет срок/ключ, устанавливает его и делает `nginx -t`/reload.
Таймер повторяется каждые 12 часов; после завершения DNS можно запустить
`systemctl start platerra-certificate.service` вручную.

Почтовые записи DNS не меняются. При появлении AAAA она должна вести на этот
же сервер; скрипт проверяет IPv4, доступность HTTP-01 снаружи проверяет LE.

## Откат

Для отключения Platerra-маршрутизации восстановить исходный landing без override:

```sh
sudo docker compose -f /home/user1/l4desk-landing/docker-compose.yml \
  up -d --no-deps --no-build landing
```

Остановить только Platerra: `docker compose -f deploy/compose.yml stop website`.
Для возврата предыдущей версии Platerra выставить сохранённый RELEASE_TAG
и пересоздать только website; входящий nginx использует динамический Docker DNS.
DNS-откат выполняется у регистратора; старый WordPress в этом деплое не меняется.
