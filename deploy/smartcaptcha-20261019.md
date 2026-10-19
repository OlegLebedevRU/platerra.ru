# SmartCaptcha — 2026-10-19

По запросу владельца contact relay переключён с native на smartcaptcha.
Существующий серверный ключ сохранён в защищённом env-файле; в Git ключей нет.
Compose выбирает `${CAPTCHA_PROVIDER:-smartcaptcha}`. Пересоздан только contact
с прежним образом; сборка сайта и изменение email gateway не потребовались.
Защищённая резервная копия серверной конфигурации сохранена для отката.

Публичный `/api/captcha/challenge`: 200, provider=smartcaptcha, no-store.
Контактная форма с корректным Origin отклоняет пустой и неверный токены с 400.
Реальные Yandex widget и iframe загружаются в Edge без ошибок JavaScript,
включая `/contacts/?topic=leo4#message`, куда ведут ссылки Leo4.
Сайты Platerra и Leo4 отвечают HTTPS 200, contact healthy.

Проверены `docker compose config`, прежний image, diff и отсутствие секретов
в изменённых файлах. Код не менялся. Ручное прохождение CAPTCHA и отправка
писем в этой задаче не выполнялись.
