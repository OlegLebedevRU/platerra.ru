# Email sender: адрес Platerra для отдельного канала

Исходник предоставлен владельцем: `send-email.py`. Блок `EMAIL_FROM_PL` ранее
читал `L4_EMAIL_FROM_PLATERRA`, но отправка его не использовала.

Теперь `device_id == "platerra-landing"` выбирает `L4_EMAIL_FROM_PLATERRA`.
Все остальные каналы сохраняют `L4_EMAIL_FROM_L4DESK`, с совместимым fallback
на прежнюю переменную `L4_EMAIL_FROM`. Выбранный адрес используется одновременно
в MIME-заголовке From и `FromEmailAddress` запроса Postbox.
Произвольное поле sender из входящего JSON игнорируется.

Если адрес Platerra не настроен, его канал возвращает ошибку, а не отправляет
от L4Desk. Каналы L4Desk и терминалов продолжают использовать прежний адрес.
Успешный ответ дополнен полем `sender`; relay Platerra проверяет его совпадение
с `CONTACT_SENDER_EMAIL=noreply@platerra.ru`.

## Публикация функции

В текущей облачной версии точка входа ссылается на `l4desk-platerra.handler`.
Для загрузки одним Python-файлом подготовлен `l4desk-platerra.py` — точная копия
канонического `send-email.py`; оставить текущую точку входа. Импорт проверен.
Загрузка `send-email.py` при этом entrypoint приводит к HandlerImportError,
поскольку имя модуля должно совпадать с именем загруженного файла.
`l4desk-platerra.py` и `index.py` — локальные копии для публикации, исключённые из Git.

`function.zip` — подготовленный локальный пакет, исключённый из Git:

```text
index.py          # содержимое send-email.py
requirements.txt  # boto3
```

Загрузить пакет новой версией **существующей** функции шлюза, entrypoint
`index.handler`. Сохранить текущие runtime, память, timeout, service account,
монтирование Object Storage, остальные переменные и старую версию для отката.
Не создавать новый шлюз и не менять его URL.

Переменные окружения:

```dotenv
L4_EMAIL_FROM_L4DESK=noreply@l4desk.ru
L4_EMAIL_FROM_PLATERRA=noreply@platerra.ru
```

Существующие ACCESS_KEY_ID/SECRET_ACCESS_KEY, параметры Postbox и хранения
остаются прежними. Адрес/домен Platerra должен быть подтверждён в Postbox.
Само значение переменной не является доказательством разрешения отправки.

После загрузки функции проверить POST по существующему адресу
`/backend-api/v1/send-email/platerra-landing`: ответ должен содержать
`status=sent`, `sender=noreply@platerra.ru` и `postbox_message_id`.
В полученном проверочном письме сверить From. Затем включить доставку relay
и опубликовать браузерную форму из подготовленной ветки.

Автоматическая публикация функции пока не выполнена: локальная авторизация
`yc` истекла. Пакет готов для загрузки через консоль владельца либо CLI после
восстановления доступа. Изменять только sender правило; старые consumers сохраняются.

## Проверки

Ruff/format, Pyright и unit tests с mock Postbox; реальных писем эти tests
не отправляют. Проверяются оба уровня From для Platerra, L4Desk и терминала,
отказ без Platerra-конфигурации и игнорирование попытки подмены sender в JSON.
