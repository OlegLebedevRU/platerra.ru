# Инструкция по установке ПО FORPAY v 3.x

Инструкция по установке ПО
FORPAY
v
3.x
Рекомендуемые конфигурации
ОС:
1)
Windows 7 +
SQL Express
2005;
2)
Windows XP SP3 + .NET Framework 3.5 SP1 + SQL Express 2005
Запуск инсталлятора в
Windows
7 необходимо делать от имени учетной записи Администратора!
Скриншоты инсталлятора:
После успешно выполненной инсталляции необходимо настроить связь и перезагрузить компьютер.
Порядок подготовки операционной системы
(в случае несоответствия приведенным выше конфигурациям)
Для подготовки терминала к установке ПО FORPAY v 3.0 следует выполнить следующие действия в зависимости от типа операционной системы* (Windows 7
или
Windows XP):
Windows 7
(х86)
– требуется установить
SQL
Express
2005 (
SP
3)*:
ftp://kiosk:forpay.ru@ftp.forpay.ru/SQLE
XPR32_RUS.EXE
(при установке
SQL
Express
2005 все предлагаемые настройки
оставить
по умолчанию)
После этого сразу переходим к установке ПО
FORPAY
*Для 64-разрядной версии Windows 7 (х64) – устанавливается 64-версия
MS
SQL
Express
2005 (
x
64)
Если у Вас
Windows XP
, следуйте инструкциям ниже.
Windows XP – порядок действий:
Проверка системы на наличие версии Windows XP SP3
Пуск - Выполнить - набрать "winver" - нажать Enter
.
Исходя из информации в появившемся окне убедиться что установлен пакет обновления Service Pack 3 (
Windows
XP
SP
3)
Если пакет не установлен - в зависимости от версии
Windows
скачать пакет и установить:
для русской версии
ftp://kiosk:forpay.ru@ftp.forpay.ru/Wind
owsXP-KB936929-SP3-x86-RUS.exe
для английской версии
ftp://kiosk:forpay.ru@ftp.forpay.ru/Wind
owsXP-KB936929-SP3-x86-ENU.exe
Убедиться что указанные ниже требуемые пакеты установлены
Пуск - Панель управления - Установка и удаление программ
У Вас должны быть установлены следующие компоненты:
Windows Installer 4.5
ftp://kiosk:forpay.ru@ftp.forpay.ru/Inst
aller-WindowsXP-KB942288-v3-x86.exe
.NET Framework 2.0 SP2
ftp://kiosk:forpay.ru@ftp.forpay.ru/NetF
x20SP2_x86.exe
Обновление безопасности для .
NET
Framework
2.0
SP
2
ftp://kiosk:forpay.ru@ftp.forpay.ru/NDP2
0SP2-KB958481-x86.exe
.NET Framework 3.5 SP1
ftp://kiosk:forpay.ru@ftp.forpay.ru/dotn
etfx35.exe
Обновление безопасности для .NET Framework 3.5 SP1
ftp://kiosk:forpay.ru@ftp.forpay.ru/NDP3
5SP1-KB958484-x86.exe
SQL Express 2005 (SP3)
ftp://kiosk:forpay.ru@ftp.forpay.ru/SQLE
XPR32_RUS.EXE
Опционально
- SQL Management Studio 2005 (SP3)
ftp://kiosk:forpay.ru@ftp.forpay.ru/SQLS
erver2005_SSMSEE.msi
Если какие-либо компоненты из перечисленных выше у Вас не установлены, то нужно установить их.
Устанавливать компоненты следует последовательно, в указанном выше порядке.
При установке компонентов все меню выбора установщиков следует оставить
по умолчанию
.
