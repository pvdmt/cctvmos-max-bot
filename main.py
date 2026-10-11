import os
import json
import re
import time
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from flask import Flask, request, jsonify

# ============================================================
# КОНФИГ
# ============================================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '').strip()
WEBHOOK_SECRET = os.environ.get('WEBHOOK_SECRET', '').strip()
SITE_TOKEN = os.environ.get('SITE_TOKEN', '').strip()
ADMIN_IDS = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]

API = 'https://platform-api2.max.ru'

# Постоянная папка /app/data от Bothost. Если недоступна — падаем обратно на локальный файл.
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
DATA_FILE = 'data.json'
try:
    if DATA_DIR and os.path.isdir(DATA_DIR):
        test_file = os.path.join(DATA_DIR, 'data.json')
        with open(test_file, 'a', encoding='utf-8'):
            pass
        DATA_FILE = test_file
except Exception as e:
    print('[WARN] Cannot use DATA_DIR, using local file:', e, flush=True)

SITE_URL = 'https://cctvmos.ru'
PHONE = '+7 (995) 655-04-65'

app = Flask(__name__)


def log(msg):
    try:
        print('[LOG] ' + str(msg), flush=True)
    except Exception:
        pass


# ============================================================
# ХРАНИЛИЩЕ
# ============================================================
def load_data():
    if not os.path.exists(DATA_FILE):
        return {'drafts': {}, 'leads': [], 'unknowns': [], 'custom_keys': {}}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'drafts': {}, 'leads': [], 'unknowns': [], 'custom_keys': {}}


def save_data(d):
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log('SAVE ERROR: ' + str(e))


# ============================================================
# ОТПРАВКА В MAX
# ============================================================
def api_request(method, path, params=None, body=None):
    if not BOT_TOKEN:
        log('NO TOKEN - skip API call')
        return None
    url = API + path
    headers = {
        'Authorization': BOT_TOKEN,
        'Content-Type': 'application/json',
    }
    try:
        log('API CALL ' + method + ' ' + path + ' params=' + json.dumps(params or {}, ensure_ascii=False))
        if method == 'GET':
            r = requests.get(url, headers=headers, params=params or {}, timeout=10, verify=False)
        elif method == 'POST':
            r = requests.post(url, headers=headers, params=params or {}, json=body or {}, timeout=10, verify=False)
        elif method == 'PUT':
            r = requests.put(url, headers=headers, params=params or {}, json=body or {}, timeout=10, verify=False)
        else:
            return None
        log('API RESPONSE ' + str(r.status_code) + ' body=' + r.text[:500])
        if r.status_code >= 400:
            return None
        try:
            return r.json()
        except Exception:
            return None
    except Exception as e:
        log('API ERROR ' + path + ': ' + str(e))
        return None


def send_message(user_id, text, keyboard=None):
    body = {'text': text}
    if keyboard:
        body['attachments'] = [keyboard]
    log('SEND to user_id=' + str(user_id) + ' text=' + text[:80])
    return api_request('POST', '/messages', params={'user_id': user_id}, body=body)


def answer_callback(callback_id, notification=''):
    if not callback_id:
        return None
    return api_request('POST', '/answers', params={'callback_id': callback_id},
                       body={'notification': notification})


def make_keyboard(rows):
    buttons = []
    for row in rows:
        buttons.append([{**b} for b in row])
    return {
        'type': 'inline_keyboard',
        'payload': {'buttons': buttons}
    }


def btn(text, payload=None, url=None, type_='callback'):
    b = {'type': type_, 'text': text}
    if payload:
        b['payload'] = payload
    if url:
        b['url'] = url
    return b


# ============================================================
# FAQ
# ============================================================
AUTO_REPLIES = [
    {'id': 'about', 'p': 'p', 'k': ['чем занимаетесь', 'что вы делаете', 'какие работы выполняете', 'о компании'],
     'r': 'CCTVMOS обслуживает, ремонтирует, устанавливает и модернизирует системы видеонаблюдения для бизнеса. Расскажите, что требуется на вашем объекте.'},
    {'id': 'services', 'p': 'p', 'k': ['какие услуги', 'список услуг', 'делаете ли аудит', 'что можете'],
     'r': 'Обслуживание, диагностика и ремонт, аудит, монтаж, модернизация, восстановление архива.\n\nВсе услуги: ' + SITE_URL + '/uslugi/'},
    {'id': 'objects', 'p': 'p', 'k': ['с какими объектами', 'обслуживаете тц', 'работаете с бизнес-центрами', 'типы объектов'],
     'r': 'Основной профиль — ТЦ, БЦ, магазины, офисы и склады. Укажите объект и адрес, чтобы уточнить условия.'},
    {'id': 'mo', 'p': 'p', 'k': ['московской области', 'выезд за мкад', 'в каких городах', 'за мкадом'],
     'r': 'Работаем по Москве и Московской области. Сообщите адрес — уточним возможность выезда.'},
    {'id': 'onetime', 'p': 'c', 'k': ['разовый ремонт', 'без договора', 'разовую диагностику', 'разовая работа'],
     'r': 'Можно обратиться за разовой диагностикой или ремонтом. Стоимость уточним по оборудованию и неисправности.'},
    {'id': 'existing', 'p': 'c', 'k': ['существующую систему', 'уже установлены камеры', 'действующее видеонаблюдение', 'подхватить систему'],
     'r': 'Да, рассматриваем действующие системы, в том числе после другого подрядчика. Сначала оценим состояние и доступ к оборудованию.'},
    {'id': 'multi', 'p': 'c', 'k': ['несколько объектов', 'сеть магазинов', 'несколько тц', 'один договор на объекты'],
     'r': 'Обслуживание нескольких объектов можно обсудить. Напишите число адресов, камер и желаемый регламент.'},
    {'id': 'private', 'p': 'c', 'k': ['частные дома', 'физлиц', 'на дачу', 'частный клиент', 'частный дом'],
     'r': 'Работаем и с частными объектами Москвы и МО. Опишите задачу — уточним условия.'},
    {'id': 'exp', 'p': 'c', 'k': ['сколько лет', 'опыт работы', 'как давно', 'давно работаете'],
     'r': 'Специализируемся на видеонаблюдении коммерческих объектов. Примеры: ' + SITE_URL + '/keysy/'},
    {'id': 'to_what', 'p': 'p', 'k': ['что входит в обслуживание', 'что включает то', 'что делаете по договору', 'регламент обслуживания'],
     'r': 'Проверяем камеры, запись, регистраторы, питание и соединения; при необходимости проводим профилактику. Состав работ фиксируется в договоре.'},
    {'id': 'to_freq', 'p': 'p', 'k': ['как часто требуется обслуживание', 'график профилактики', 'периодичность то'],
     'r': 'График ТО зависит от количества камер и условий эксплуатации. Предложим периодичность после оценки системы.'},
    {'id': 'to_why', 'p': 'p', 'k': ['зачем профилактика', 'зачем платить за обслуживание', 'то исправной системы'],
     'r': 'Профилактика помогает выявить неполадки записи, дисков, питания и соединений до серьёзного отказа.'},
    {'id': 'to_check', 'p': 'p', 'k': ['проверяете все камеры', 'проверка каналов', 'контроль архива', 'проверяете запись'],
     'r': 'Да, проверку согласованных каналов и архива можно включить в регламент. Периодичность определим с заказчиком.'},
    {'id': 'dvr', 'p': 'p', 'k': ['обслуживаете регистраторы', 'dvr ремонт', 'nvr ремонт', 'ремонт регистратора'],
     'r': 'Диагностируем видеорегистраторы и связанные узлы. Пришлите модель и описание проблемы.'},
    {'id': 'big', 'p': 'c', 'k': ['более 100 камер', 'большой объект', '150 камер', 'крупный объект'],
     'r': 'Для систем свыше 100 камер предусмотрен индивидуальный расчёт. Укажите число камер, регистраторов и объектов.'},
    {'id': 'reports', 'p': 'p', 'k': ['отчёты о работах', 'акты', 'отчёт для ук', 'отчётность'],
     'r': 'Акты и отчёты о выполненных работах согласуем в договоре. При необходимости учтём формат вашей УК.'},
    {'id': 'emergency', 'p': 'a', 'k': ['авария системы', 'срочная неисправность', 'отказали камеры', 'всё отключилось'],
     'r': '🚨 Сообщите адрес, что отключилось и сколько камер затронуто. Передадим обращение специалисту с приоритетом СРОЧНО.'},
    {'id': 'no_signal', 'p': 'a', 'k': ['камера перестала показывать', 'камера офлайн', 'нет изображения', 'камера не работает'],
     'r': '🚨 Уточните модель, число неработающих камер и что видно на экране. Передадим сообщение специалисту.'},
    {'id': 'black', 'p': 'a', 'k': ['чёрный экран', 'черный экран', 'чёрная картинка', 'черная картинка'],
     'r': '🚨 Чёрный экран может быть связан с питанием, сетью или регистратором. Напишите, пропало видео на одной камере или на всех.'},
    {'id': 'night', 'p': 'p', 'k': ['плохо показывает ночью', 'нет ночной съёмки', 'ик-подсветка', 'ночная съёмка'],
     'r': 'Причина может быть в ИК-подсветке, освещении или настройках. Пришлите модель и описание ночной картинки.'},
    {'id': 'blur', 'p': 'p', 'k': ['изображение мутное', 'камера размыта', 'плохая резкость', 'мутная картинка'],
     'r': 'Возможны загрязнение, конденсат или сбой фокусировки. Уточните модель и когда появилась размытость.'},
    {'id': 'drops', 'p': 'a', 'k': ['камеры отключаются', 'камеры пропадают', 'нет связи с камерами', 'постоянно отваливаются'],
     'r': '🚨 Повторные отключения бывают из-за сети, питания или кабелей. Укажите, сколько камер отключается и как часто.'},
    {'id': 'nvr_dead', 'p': 'a', 'k': ['регистратор не работает', 'nvr не включается', 'регистратор перезагружается', 'не включается регистратор'],
     'r': '🚨 Напишите модель и симптомы: не включается, перезагружается или не видит камеры. Передадим специалисту.'},
    {'id': 'no_rec', 'p': 'a', 'k': ['не записывает архив', 'нет записи', 'не сохраняется видео', 'регистратор не пишет', 'пропала запись', 'пропадает запись', 'исчезла запись'],
     'r': '🚨 Если архив не записывается, новые события могут быть потеряны. Сообщите модель регистратора и когда пропала запись.'},
    {'id': 'repair_cam', 'p': 'c', 'k': ['отремонтировать камеру', 'ремонт камеры', 'стоит ли чинить', 'ремонт вместо замены'],
     'r': 'Решение о ремонте или замене принимается после диагностики и оценки стоимости. Возможна замена отдельных камер без полной модернизации.'},
    {'id': 'partial', 'p': 'c', 'k': ['заменить часть камер', 'замена нескольких камер', 'обновить несколько камер', 'не хотим менять всё'],
     'r': 'Частичная замена возможна после проверки совместимости камер, регистратора и питания. Уточните модели оборудования.'},
    {'id': 'unstable', 'p': 'p', 'k': ['причина сбоев', 'система нестабильна', 'регулярные поломки', 'постоянные сбои'],
     'r': 'Ищем причины повторных сбоев в питании, сети, кабелях и настройках. Опишите симптомы и частоту проблем.'},
    {'id': 'storm', 'p': 'a', 'k': ['после грозы', 'скачок напряжения', 'сгорел блок питания', 'после отключения света', 'перепад напряжения', 'отключения света'],
     'r': '🚨 Если после грозы или перепада напряжения камеры не работают, не вскрывайте оборудование и не включайте его повторно при признаках повреждения. Сообщите адрес и масштаб отказа.'},
    {'id': 'hacked', 'p': 'a', 'k': ['взлом камер', 'взломали камеры', 'посторонний доступ', 'подозрительные подключения', 'камеры под вирусом'],
     'r': '🚨 Ограничьте внешний доступ к системе, если это возможно без потери записи. Сохраните сведения об инциденте и не публикуйте пароли. Передадим обращение с приоритетом СРОЧНО.'},
    {'id': 'ip', 'p': 'p', 'k': ['ip-камеры', 'цифровые камеры', 'ip видеонаблюдение', 'работаете с ip'],
     'r': 'Да, работаем с IP-системами. Для уточнения задачи пришлите производителя и модели камер.'},
    {'id': 'analog', 'p': 'p', 'k': ['аналоговое видеонаблюдение', 'аналоговые камеры', 'ahd', 'tvi', 'cvi'],
     'r': 'Рассматриваем аналоговые AHD, TVI, CVI и смешанные системы. Пришлите модели оборудования.'},
    {'id': 'brands', 'p': 'c', 'k': ['hikvision', 'hiwatch', 'dahua', 'какие бренды'],
     'r': 'Проверим возможность работ с Hikvision, HiWatch, Dahua и другими брендами по конкретной модели. Пришлите название оборудования.'},
    {'id': 'add_cam', 'p': 'c', 'k': ['добавить камеры', 'расширить видеонаблюдение', 'поставить ещё камеры', 'дополнительные камеры'],
     'r': 'Возможность расширения зависит от свободных каналов, сети, питания и архива. Напишите, сколько камер нужно добавить.'},
    {'id': 'unite', 'p': 'c', 'k': ['объединить камеры', 'несколько зданий', 'единая система', 'центральный пост'],
     'r': 'Объединение нескольких зданий возможно при подходящей инфраструктуре. Уточните адреса и задачи общего поста.'},
    {'id': 'remote', 'p': 'p', 'k': ['смотреть камеры удалённо', 'просмотр с телефона', 'удалённый доступ', 'из другого офиса'],
     'r': 'Удалённый просмотр зависит от оборудования и сети. Поможем оценить безопасный вариант доступа.'},
    {'id': 'spares', 'p': 'c', 'k': ['запчасти', 'детали в наличии', 'блок питания есть', 'оборудование под заказ'],
     'r': 'Наличие и сроки поставки зависят от модели оборудования. Пришлите список или фото маркировки — уточним.'},
    {'id': 'lostpass', 'p': 'c', 'k': ['забыли пароль', 'нет пароля от регистратора', 'предыдущий подрядчик не передал доступ', 'не можем зайти в регистратор'],
     'r': 'Уточним модель и законное право доступа к оборудованию. После проверки специалист предложит решение.'},
    {'id': 'archive_lost', 'p': 'a', 'k': ['пропал архив', 'исчезли записи', 'не найти видео', 'пропала запись'],
     'r': '🚨 Архив мог исчезнуть из-за перезаписи, неисправности диска или ошибки времени. Не перезаписывайте проблемный носитель. Укажите период и модель регистратора.'},
    {'id': 'archive_rec', 'p': 'a', 'k': ['восстановить архив', 'вернуть удалённую запись', 'восстановить видео', 'восстановление записей'],
     'r': '🚨 Восстановление возможно не всегда — зависит от перезаписи и состояния диска. Не записывайте новые данные на проблемный носитель до консультации.'},
    {'id': 'archive_days', 'p': 'p', 'k': ['сколько дней хранится', 'срок хранения записи', 'глубина архива', 'архив за месяц'],
     'r': 'Срок хранения зависит от числа камер, качества видео, режима записи и объёма дисков. Рассчитаем нужную ёмкость.'},
    {'id': 'archive_deep', 'p': 'c', 'k': ['увеличить глубину архива', 'хранить дольше', 'увеличить запись', 'увеличить архив'],
     'r': 'Можно увеличить дисковое пространство или изменить параметры записи. Сначала проверим возможности регистратора.'},
    {'id': 'archive_usb', 'p': 'p', 'k': ['сохранить на флешку', 'выгрузить видео', 'экспорт архива', 'как скачать видео'],
     'r': 'Экспорт архива зависит от модели системы. Напишите модель и необходимый период видео.'},
    {'id': 'motion', 'p': 'p', 'k': ['запись по движению', 'пишет только при движении', 'экономия места', 'детекция движения'],
     'r': 'Во многих системах доступна запись по движению. Проверим поддержку функции и корректность её работы.'},
    {'id': 'price_to', 'p': 'c', 'k': ['сколько стоит обслуживание', 'цена договора', 'тарифы на то', 'стоимость то'],
     'r': 'Обслуживание — от 19 900 ₽/мес. Точная стоимость зависит от системы и объекта. Подробности — кнопка «💰 Тарифы».'},
    {'id': 'price_visit', 'p': 'c', 'k': ['сколько стоит выезд', 'цена диагностики', 'осмотр платный', 'стоимость выезда'],
     'r': 'Цена диагностики зависит от адреса и оборудования. Напишите симптомы и местоположение — уточним стоимость.'},
    {'id': 'time_visit', 'p': 'c', 'k': ['как быстро приедет', 'срочный выезд', 'можете сегодня', 'когда приедете'],
     'r': 'Приём заявок — 24/7. Реальное время выезда специалист согласует с учётом адреса и доступности.'},
    {'id': 'warranty', 'p': 'c', 'k': ['какие гарантии', 'гарантия на работы', 'если снова сломается'],
     'r': 'Гарантийные условия согласуются для конкретных работ и закрепляются в документах. Уточните вид услуги.'},
    {'id': 'contract', 'p': 'c', 'k': ['работаете по договору', 'безналичный расчёт', 'нужен счёт', 'закрывающие документы'],
     'r': 'Работу по договору, счёту и актам согласуем с менеджером. Сообщите требования бухгалтерии.'},
    {'id': 'kp', 'p': 'c', 'k': ['коммерческое предложение', 'пришлите кп', 'рассчитайте объект', 'хочу кп'],
     'r': 'Для КП укажите адрес и тип объекта, число камер и нужные услуги. Менеджер уточнит данные для расчёта.'},
    {'id': 'anytime', 'p': 'p', 'k': ['заявки 24/7', 'можно написать ночью', 'работаете в выходные'],
     'r': 'Да, заявки принимаются круглосуточно. Время ответа и выезда подтверждается отдельно.'},
    {'id': 'echd', 'p': 'p', 'k': ['ецхд', 'единый центр хранения', 'сбой ецхд', 'подключение к ецхд'],
     'r': 'Рассматриваем задачи по сопровождению ЕЦХД и восстановлению передачи после сбоев. Уточните конфигурацию и проблему.'},
    {'id': 'human', 'p': 'c', 'k': ['живой менеджер', 'позовите оператора', 'с человеком', 'хочу поговорить'],
     'r': 'Передадим ваш вопрос менеджеру.\n\n📞 ' + PHONE},
    {'id': 'order', 'p': 'c', 'k': ['как оставить заявку', 'вызвать специалиста', 'заказать услугу', 'оставить заявку'],
     'r': 'Нажмите «📝 Оставить заявку» и укажите имя, телефон, тип объекта и услугу.'},
    {'id': 'pay', 'p': 'c', 'k': ['оплатить картой', 'оплата по сбп', 'оплатить по qr', 'принимаете карты'],
     'r': 'Способ оплаты уточнит менеджер. Напишите, требуется ли счёт для организации или оплата как физлицо.'},
    {'id': '44fz', 'p': 'c', 'k': ['44-фз', 'госзакупки', 'бюджетная организация', 'контракт с госучреждением'],
     'r': 'Пришлите требования закупки и документации. Менеджер уточнит возможность участия и оформления договора.'},
]

RULES_TITLES = {
    'about': 'О компании', 'services': 'Список услуг', 'objects': 'Типы объектов', 'mo': 'Москва и МО',
    'onetime': 'Разовый ремонт', 'existing': 'Существующая система', 'multi': 'Несколько объектов',
    'private': 'Частные объекты', 'exp': 'Опыт компании',
    'to_what': 'Что входит в ТО', 'to_freq': 'Частота ТО', 'to_why': 'Зачем профилактика',
    'to_check': 'Проверка камер и архива', 'dvr': 'Регистраторы', 'big': 'Система 100+ камер',
    'reports': 'Отчёты и акты', 'emergency': 'АВАРИЯ системы',
    'no_signal': 'Нет изображения', 'black': 'Чёрный экран', 'night': 'Ночная съёмка',
    'blur': 'Мутное изображение', 'drops': 'Камеры отключаются', 'nvr_dead': 'Регистратор не работает',
    'no_rec': 'Нет записи архива', 'repair_cam': 'Ремонт или замена',
    'partial': 'Частичная замена', 'unstable': 'Причины сбоев',
    'storm': 'После грозы / скачков', 'hacked': 'Взлом камер',
    'ip': 'IP-камеры', 'analog': 'Аналоговые системы', 'brands': 'Hikvision, Dahua',
    'add_cam': 'Добавить камеры', 'unite': 'Объединение зданий', 'remote': 'Удалённый доступ',
    'spares': 'Запчасти', 'lostpass': 'Восстановление пароля',
    'archive_lost': 'Пропал архив', 'archive_rec': 'Восстановление',
    'archive_days': 'Срок хранения', 'archive_deep': 'Увеличить архив',
    'archive_usb': 'Экспорт на флешку', 'motion': 'Запись по движению',
    'price_to': 'Стоимость ТО', 'price_visit': 'Стоимость выезда', 'time_visit': 'Время выезда',
    'warranty': 'Гарантия', 'contract': 'Договор', 'kp': 'Коммерческое предложение',
    'anytime': 'Заявки 24/7', 'echd': 'ЕЦХД', 'human': 'Связь с менеджером',
    'order': 'Как оставить заявку', 'pay': 'Способы оплаты', '44fz': '44-ФЗ',
}

RULES_GROUPS = [
    {'name': 'Компания и услуги', 'emoji': '◻️', 'ids': ['about', 'services', 'objects', 'mo', 'onetime', 'existing', 'multi', 'private', 'exp']},
    {'name': 'Техобслуживание', 'emoji': '🛠', 'ids': ['to_what', 'to_freq', 'to_why', 'to_check', 'dvr', 'big', 'reports', 'emergency']},
    {'name': 'Ремонт и аварии', 'emoji': '🚨', 'ids': ['no_signal', 'black', 'night', 'blur', 'drops', 'nvr_dead', 'no_rec', 'repair_cam', 'partial', 'unstable', 'storm', 'hacked']},
    {'name': 'Оборудование', 'emoji': '⚙️', 'ids': ['ip', 'analog', 'brands', 'add_cam', 'unite', 'remote', 'spares', 'lostpass']},
    {'name': 'Архив', 'emoji': '💾', 'ids': ['archive_lost', 'archive_rec', 'archive_days', 'archive_deep', 'archive_usb', 'motion']},
    {'name': 'Цены и договоры', 'emoji': '💼', 'ids': ['price_to', 'price_visit', 'time_visit', 'warranty', 'contract', 'kp', 'anytime', 'echd', 'human', 'order', 'pay', '44fz']},
]

RULE_NUMBERS = {}
_n = 0
for g in RULES_GROUPS:
    for rid in g['ids']:
        _n += 1
        RULE_NUMBERS[_n] = rid

RULE_ID_TO_NUM = {v: k for k, v in RULE_NUMBERS.items()}


def group_start_index(idx):
    s = 1
    for i in range(idx):
        s += len(RULES_GROUPS[i]['ids'])
    return s


def group_by_number(num):
    s = 1
    for g in RULES_GROUPS:
        e = s + len(g['ids']) - 1
        if s <= num <= e:
            return {'group': g, 'start': s, 'end': e}
        s = e + 1
    return None


def rule_title(rid):
    return RULES_TITLES.get(rid, rid)


# ============================================================
# ПОИСК
# ============================================================
def normalize(t):
    t = t.lower().replace('ё', 'е')
    t = re.sub(r'[^\wа-я0-9\s]', ' ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return ' ' + t + ' '


def escape_re(s):
    return re.escape(s)


def split_fragments(text):
    t = re.sub(r'([.!?])\s+', r'\1|', text)
    t = re.sub(r'\s+(и ещё|а ещё|ещё|также|плюс|а также|и)\s+', '|', t, flags=re.IGNORECASE)
    parts = [x.strip() for x in t.split('|') if len(x.strip()) >= 4]
    return parts if parts else [text.strip()]


def match_rule(text, rules):
    norm = normalize(text)
    words = [w for w in norm.strip().split() if len(w) > 2]
    best, best_score, best_prio = None, 0, 0
    for rule in rules:
        score = 0
        for kw in rule['k']:
            kwn = normalize(kw).strip()
            if ' ' in kwn:
                if ' ' + kwn + ' ' in norm:
                    score += 4
                elif kwn in norm:
                    score += 2
            else:
                if re.search(r'\b' + escape_re(kwn) + r'\b', norm):
                    score += 2
                elif any(len(w) >= 5 and len(kwn) >= 5 and w.startswith(kwn[:5]) for w in words):
                    score += 1
        if score == 0:
            continue
        prio = 3 if rule['p'] == 'a' else (2 if rule['p'] == 'c' else 1)
        if score > best_score or (score == best_score and prio > best_prio):
            best, best_score, best_prio = rule, score, prio
    return {'rule': best, 'score': best_score} if best_score >= 2 else None


def find_replies(text, data):
    custom = data.get('custom_keys', {})
    extended = []
    for r in AUTO_REPLIES:
        extra = custom.get(r['id'], [])
        extended.append({**r, 'k': r['k'] + extra})
    frags = split_fragments(text)
    matched = {}
    for frag in frags:
        res = match_rule(frag, extended)
        if res:
            rid = res['rule']['id']
            if rid not in matched or res['score'] > matched[rid]['score']:
                matched[rid] = res
    return [v['rule'] for v in matched.values()]


# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_menu_kb():
    return make_keyboard([
        [btn('📝 Оставить заявку', 'menu:lead'), btn('📞 Позвонить', 'menu:phone')],
        [btn('🌐 Услуги', 'menu:services'), btn('💰 Тарифы', 'menu:tariffs')],
        [btn('📁 Примеры работ', 'menu:cases'), btn('✍️ Менеджер', 'menu:human')],
    ])


def admin_menu_kb():
    return make_keyboard([
        [btn('📊 Статистика', 'adm:stats'), btn('📋 Заявки', 'adm:list')],
        [btn('🧠 Непонятые', 'adm:unknowns'), btn('📚 Правила', 'adm:rules')],
    ])


# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ ОТ КЛИЕНТА
# ============================================================
def handle_client_message(user_id, text, first_name, username, data):
    log('CLIENT MSG from ' + str(user_id) + ' (' + first_name + '): ' + text[:80])

    draft = data['drafts'].get(str(user_id))
    if draft and draft.get('step'):
        if text in ('/start', '/cancel', 'Меню'):
            data['drafts'].pop(str(user_id), None)
            save_data(data)
            send_message(user_id, 'Хорошо, отменил. Чем помочь?', main_menu_kb())
            return
        continue_lead(draft, user_id, text, first_name, username, data)
        return

    if text in ('/start', '/menu', 'Меню'):
        send_message(user_id,
                     'Здравствуйте, ' + first_name + '!\n\nЭто бот CCTVMOS — обслуживание видеонаблюдения для коммерческих объектов Москвы.\n\nВыберите раздел в меню или напишите вопрос.',
                     main_menu_kb())
        return

    if text == '📝 Оставить заявку':
        data['drafts'][str(user_id)] = {'step': 'name'}
        save_data(data)
        send_message(user_id, 'Отлично! Давайте оформим заявку за 1 минуту.\n\nКак вас зовут?')
        return

    matches = find_replies(text, data)
    log('MATCHED: ' + str([m['id'] for m in matches]))

    if not matches:
        data['unknowns'].append({'text': text, 'user_id': user_id, 'name': first_name,
                                 'username': username, 'ts': int(time.time())})
        data['unknowns'] = data['unknowns'][-100:]
        save_data(data)
        for admin_id in ADMIN_IDS:
            send_message(admin_id,
                         '🤔 Не понял вопрос\n\n👤 ' + first_name + '\n🔗 @' + (username or '—') + '\n🆔 ' + str(user_id) + '\n\n💬 ' + text)
        send_message(user_id, '✅ Спасибо, ' + first_name + '! Сообщение передано менеджеру.', main_menu_kb())
        return

    urgent = any(m['p'] == 'a' for m in matches)
    if len(matches) == 1:
        reply = matches[0]['r']
        if matches[0]['p'] == 'a':
            reply += '\n\nЕсли нужно — позвоните: ' + PHONE
    elif len(matches) <= 3 and not urgent:
        reply = 'У вас несколько вопросов — отвечу по порядку:\n\n'
        for m in matches:
            reply += '▫️ ' + m['r'] + '\n\n'
        reply += 'Если нужно уточнить — напишите или позвоните.'
    else:
        reply = 'Похоже, у вас несколько проблем. Передам специалисту СРОЧНО.\n\nТемы:\n'
        for m in matches[:5]:
            first = m['r'].split('\n')[0].replace('🚨 ', '')
            reply += '▫️ ' + first + '\n'
        reply += '\nЕсли срочно — позвоните: ' + PHONE

    send_message(user_id, reply, main_menu_kb())

    if urgent:
        header = '🚨 СРОЧНО — сообщение от клиента\n\n👤 ' + first_name + '\n🔗 @' + (username or '—') + '\n🆔 ' + str(user_id) + '\n\n💬 ' + text + '\n\n🎯 Распознано тем: ' + str(len(matches))
    else:
        header = '🤖 Автоответ отправлен клиенту\n\n👤 ' + first_name + '\n🔗 @' + (username or '—') + '\n🆔 ' + str(user_id) + '\n\n💬 ' + text + '\n\n🎯 Распознано тем: ' + str(len(matches))
    for admin_id in ADMIN_IDS:
        send_message(admin_id, header)


# ============================================================
# СЦЕНАРИЙ ЗАЯВКИ
# ============================================================
def continue_lead(draft, user_id, text, first_name, username, data):
    step = draft['step']
    if step == 'name':
        draft['name'] = text[:100]
        draft['step'] = 'phone'
        save_data(data)
        send_message(user_id, 'Спасибо, ' + draft['name'] + '!\n\nУкажите номер телефона.')
        return
    if step == 'phone':
        digits = re.sub(r'\D', '', text)
        if len(digits) < 10:
            send_message(user_id, 'Похоже, номер неполный. Минимум 10 цифр.')
            return
        draft['phone'] = text[:30]
        draft['step'] = 'object'
        save_data(data)
        rows = [
            [btn('🏬 Торговый центр', 'obj:tc'), btn('🏢 Бизнес-центр', 'obj:bc')],
            [btn('🛒 Магазин', 'obj:shop'), btn('📦 Склад', 'obj:warehouse')],
            [btn('🏡 Частный объект', 'obj:private'), btn('❓ Другое', 'obj:other')],
        ]
        send_message(user_id, 'Какой у вас объект?', make_keyboard(rows))
        return
    if step == 'object':
        draft['object'] = text[:100]
        draft['step'] = 'service'
        save_data(data)
        rows = [
            [btn('🛠 Обслуживание', 'srv:obsluzh'), btn('🔧 Ремонт', 'srv:remont')],
            [btn('📋 Аудит', 'srv:audit'), btn('📷 Монтаж', 'srv:montazh')],
            [btn('⚡ Модернизация', 'srv:modern'), btn('💾 Архив', 'srv:archive')],
        ]
        send_message(user_id, 'Что вас интересует?', make_keyboard(rows))
        return
    if step == 'service':
        draft['service'] = text[:100]
        finalize_lead(draft, user_id, first_name, username, data)
        return


def finalize_lead(draft, user_id, first_name, username, data):
    now = time.localtime()
    num = '{:02d}{:02d}-{:02d}{:02d}'.format(now.tm_mday, now.tm_mon, now.tm_hour, now.tm_min)
    lead = {
        'number': num,
        'name': draft.get('name', ''),
        'phone': draft.get('phone', ''),
        'object': draft.get('object', ''),
        'service': draft.get('service', ''),
        'source': 'bot',
        'client_name': first_name,
        'client_username': username,
        'user_id': user_id,
        'created_at': int(time.time()),
    }
    data['leads'].append(lead)
    data['leads'] = data['leads'][-500:]
    data['drafts'].pop(str(user_id), None)
    save_data(data)

    msg = ('📩 Новая заявка из бота №' + num + '\n\n'
           '👤 ' + lead['name'] + '\n📞 ' + lead['phone'] + '\n🏢 ' + lead['object'] + '\n🔧 ' + lead['service'] + '\n\n'
           '🔗 @' + (username or '—') + '\n🆔 ' + str(user_id))
    for admin_id in ADMIN_IDS:
        send_message(admin_id, msg)

    send_message(user_id,
                 '✅ Заявка №' + num + ' принята!\n\n📞 ' + lead['phone'] + '\n🏢 ' + lead['object'] + '\n🔧 ' + lead['service'] + '\n\nМенеджер свяжется с вами.',
                 main_menu_kb())


# ============================================================
# ОБРАБОТКА СООБЩЕНИЙ АДМИНА
# ============================================================
def handle_admin_message(user_id, text, data):
    log('ADMIN MSG from ' + str(user_id) + ': ' + text[:80])

    if text in ('/start', '/help', 'Меню'):
        send_message(user_id,
                     '👋 Админ-панель CCTVMOS\n\nКоманды:\n'
                     '/stats — статистика\n/list — последние заявки\n'
                     '/unknowns — непопадания\n/rules — правила FAQ\n'
                     '/find <номер> — найти заявку',
                     admin_menu_kb())
        return
    if text == '/stats':
        leads = data['leads']
        today = [l for l in leads if l['created_at'] >= time.time() - 86400]
        week = [l for l in leads if l['created_at'] >= time.time() - 7 * 86400]
        send_message(user_id, '📊 Заявок всего: ' + str(len(leads)) + '\nЗа 24 часа: ' + str(len(today)) + '\nЗа 7 дней: ' + str(len(week)), admin_menu_kb())
        return
    if text == '/list':
        last = data['leads'][-10:][::-1]
        out = '📋 Последние заявки:\n\n'
        for l in last:
            src = '🌐' if l.get('source') == 'site' else '🤖'
            out += src + ' №' + l['number'] + ' — ' + l['name'] + '\n🏢 ' + l['object'] + ' · 🔧 ' + l['service'] + '\n📞 ' + l['phone'] + '\n\n'
        send_message(user_id, out or 'Заявок нет.', admin_menu_kb())
        return
    if text.startswith('/find '):
        num = text[6:].strip()
        for l in data['leads']:
            if l['number'] == num:
                src = 'Сайт' if l.get('source') == 'site' else 'Бот'
                send_message(user_id,
                             '📋 Заявка №' + l['number'] + ' (' + src + ')\n\n👤 ' + l['name'] + '\n📞 ' + l['phone'] + '\n🏢 ' + l['object'] + '\n🔧 ' + l['service'],
                             admin_menu_kb())
                return
        send_message(user_id, 'Заявка №' + num + ' не найдена.', admin_menu_kb())
        return
    if text == '/unknowns':
        unknowns = data['unknowns'][-10:][::-1]
        out = '🧠 Непонятые (' + str(len(unknowns)) + '):\n\n'
        rows = []
        for i, u in enumerate(unknowns, 1):
            preview = u['text'][:60].replace('\n', ' ')
            out += str(i) + '. ' + u['name'] + ' — «' + preview + '…»\n'
            rows.append([btn('🎯 ' + str(i) + '. ' + u['name'], 'learn:unk:' + str(u['user_id']) + ':' + str(u['ts']))])
        send_message(user_id, out, make_keyboard(rows) if rows else None)
        return
    if text == '/rules':
        rows = [[btn(g['emoji'] + ' ' + g['name'], 'rules:grp:' + str(i))] for i, g in enumerate(RULES_GROUPS)]
        send_message(user_id, '📚 Правила FAQ — выберите группу:', make_keyboard(rows))
        return

    # Любое другое сообщение от админа — показываем меню
    send_message(user_id, '👋 Что нужно сделать?', admin_menu_kb())


# ============================================================
# CALLBACK
# ============================================================
def handle_callback(user_id, payload, data):
    log('CALLBACK from ' + str(user_id) + ' payload=' + payload)
    is_admin = user_id in ADMIN_IDS

    if payload == 'menu:lead':
        data['drafts'][str(user_id)] = {'step': 'name'}
        save_data(data)
        send_message(user_id, 'Как вас зовут?')
        return
    if payload == 'menu:phone':
        send_message(user_id, '📞 ' + PHONE + '\n\nЗвонок — сразу ответим или перезвоним.', main_menu_kb())
        return
    if payload == 'menu:services':
        send_message(user_id, 'Все услуги: ' + SITE_URL + '/uslugi/', main_menu_kb())
        return
    if payload == 'menu:tariffs':
        send_message(user_id,
                     'Тарифы и цены: ' + SITE_URL + '/tarify/\n\nБазовый — от 19 900 ₽/мес, Стандарт — от 29 900 ₽/мес, Расширенный — от 39 900 ₽/мес.',
                     main_menu_kb())
        return
    if payload == 'menu:cases':
        send_message(user_id, 'Наши объекты: ' + SITE_URL + '/keysy/', main_menu_kb())
        return
    if payload == 'menu:human':
        send_message(user_id, 'Свяжитесь с менеджером:\n\n📞 ' + PHONE, main_menu_kb())
        return

    if is_admin and payload == 'adm:stats':
        handle_admin_message(user_id, '/stats', data)
        return
    if is_admin and payload == 'adm:list':
        handle_admin_message(user_id, '/list', data)
        return
    if is_admin and payload == 'adm:unknowns':
        handle_admin_message(user_id, '/unknowns', data)
        return
    if is_admin and payload == 'adm:rules':
        handle_admin_message(user_id, '/rules', data)
        return

    if is_admin and payload.startswith('rules:grp:'):
        idx = int(payload[10:])
        g = RULES_GROUPS[idx]
        out = g['emoji'] + ' ' + g['name'] + '\n\n'
        n = group_start_index(idx)
        for rid in g['ids']:
            out += str(n) + '. ' + rule_title(rid) + '\n'
            n += 1
        send_message(user_id, out, admin_menu_kb())
        return

    if is_admin and payload.startswith('learn:unk:'):
        parts = payload.split(':')
        unk_user_id = parts[2]
        unk_ts = parts[3]
        found = None
        for u in data['unknowns']:
            if str(u['user_id']) == unk_user_id and str(u['ts']) == unk_ts:
                found = u
                break
        if not found:
            send_message(user_id, 'Уже присвоено или удалено.')
            return
        rows = [[btn(g['emoji'] + ' ' + g['name'], 'learn:grp:' + str(i) + ':' + unk_user_id + ':' + unk_ts)]
                for i, g in enumerate(RULES_GROUPS)]
        send_message(user_id, '📝 Присваиваем правило для:\n\n«' + found['text'][:80] + '»\n\nВыберите группу:', make_keyboard(rows))
        return

    if is_admin and payload.startswith('learn:grp:'):
        parts = payload.split(':')
        idx = int(parts[2])
        unk_user_id = parts[3]
        unk_ts = parts[4]
        g = RULES_GROUPS[idx]
        rows = []
        n = group_start_index(idx)
        for rid in g['ids']:
            rows.append([btn(str(n) + '. ' + rule_title(rid), 'learn:rule:' + str(n) + ':' + unk_user_id + ':' + unk_ts)])
            n += 1
        send_message(user_id, g['emoji'] + ' ' + g['name'] + '\n\nВыберите правило:', make_keyboard(rows))
        return

    if is_admin and payload.startswith('learn:rule:'):
        parts = payload.split(':')
        num = int(parts[2])
        unk_user_id = parts[3]
        unk_ts = parts[4]
        rule_id = RULE_NUMBERS.get(num)
        if not rule_id:
            send_message(user_id, 'Правило не найдено.')
            return
        found = None
        for i, u in enumerate(data['unknowns']):
            if str(u['user_id']) == unk_user_id and str(u['ts']) == unk_ts:
                found = data['unknowns'].pop(i)
                break
        if not found:
            send_message(user_id, 'Уже присвоено.')
            return
        phrase = found['text'].lower()[:100]
        custom = data.setdefault('custom_keys', {})
        arr = custom.setdefault(rule_id, [])
        if phrase not in arr:
            arr.append(phrase)
            custom[rule_id] = arr[-50:]
        save_data(data)
        send_message(user_id,
                     '✅ Присвоено правилу «' + rule_title(rule_id) + '»:\n\n«' + phrase + '»\n\nТеперь это сообщение будет вести к ответу FAQ.',
                     admin_menu_kb())
        return

    draft = data['drafts'].get(str(user_id))
    if not draft:
        return
    if payload.startswith('obj:') and draft.get('step') == 'object':
        key = payload[4:]
        labels = {'tc': 'Торговый центр', 'bc': 'Бизнес-центр', 'shop': 'Магазин / ритейл',
                  'warehouse': 'Склад / офис', 'private': 'Частный объект', 'other': 'Другое'}
        draft['object'] = labels.get(key, key)
        draft['step'] = 'service'
        save_data(data)
        rows = [
            [btn('🛠 Обслуживание', 'srv:obsluzh'), btn('🔧 Ремонт', 'srv:remont')],
            [btn('📋 Аудит', 'srv:audit'), btn('📷 Монтаж', 'srv:montazh')],
            [btn('⚡ Модернизация', 'srv:modern'), btn('💾 Архив', 'srv:archive')],
        ]
        send_message(user_id, 'Что вас интересует?', make_keyboard(rows))
        return
    if payload.startswith('srv:') and draft.get('step') == 'service':
        key = payload[4:]
        labels = {'obsluzh': 'Техническое обслуживание', 'remont': 'Диагностика и ремонт',
                  'audit': 'Технический аудит', 'montazh': 'Монтаж камер',
                  'modern': 'Модернизация', 'archive': 'Восстановление архива'}
        draft['service'] = labels.get(key, key)
        finalize_lead(draft, user_id, '', '', data)
        return


# ============================================================
# ВЕБХУК MAX
# ============================================================
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        raw = request.get_data(as_text=True)
        log('RAW WEBHOOK: ' + raw[:1500])

        secret = request.headers.get('X-Max-Bot-Api-Secret', '')
        if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
            log('WEBHOOK SECRET MISMATCH')
            return jsonify({'ok': False}), 403

        update = request.get_json(silent=True) or {}
        update_type = update.get('update_type', '')
        log('UPDATE TYPE: ' + update_type)

        data = load_data()

        if update_type == 'message_created':
            msg = update.get('message', {}) or {}
            sender = msg.get('sender', {}) or {}
            user_id = sender.get('user_id')
            body = msg.get('body', {}) or {}
            text = (body.get('text', '') or '').strip()
            first_name = sender.get('first_name') or sender.get('name') or 'клиент'
            username = sender.get('username', '') or ''
            log('PARSED: user_id=' + str(user_id) + ' text=' + repr(text[:80]))
            if not user_id or not text:
                log('SKIP: empty user_id or text')
                return jsonify({'ok': True})
            if user_id in ADMIN_IDS:
                handle_admin_message(user_id, text, data)
            else:
                handle_client_message(user_id, text, first_name, username, data)
            return jsonify({'ok': True})

        if update_type == 'message_callback':
            cb = update.get('callback', {}) or {}
            payload = cb.get('payload', '') or ''
            user = cb.get('user', {}) or {}
            user_id = user.get('user_id')
            log('CALLBACK: user_id=' + str(user_id) + ' payload=' + payload)
            if not user_id:
                return jsonify({'ok': True})
            handle_callback(user_id, payload, data)
            return jsonify({'ok': True})

        if update_type == 'bot_started':
            user = update.get('user') or {}
            user_id = user.get('user_id')
            log('BOT_STARTED: user_id=' + str(user_id))
            if user_id:
                if user_id in ADMIN_IDS:
                    handle_admin_message(user_id, '/start', data)
                else:
                    first_name = user.get('first_name', 'клиент')
                    handle_client_message(user_id, '/start', first_name, '', data)
            return jsonify({'ok': True})

        log('UNKNOWN UPDATE TYPE: ' + update_type)
        return jsonify({'ok': True})
    except Exception as e:
        log('WEBHOOK ERROR: ' + str(e))
        import traceback
        log('TRACEBACK: ' + traceback.format_exc())
        return jsonify({'ok': True})


# ============================================================
# ЗАЯВКИ С САЙТА
# ============================================================
@app.route('/site-lead', methods=['POST'])
def site_lead():
    try:
        raw = request.get_data(as_text=True)
        log('SITE LEAD RAW: ' + raw[:1500])

        secret = request.headers.get('X-Site-Token', '')
        if SITE_TOKEN and secret != SITE_TOKEN:
            log('SITE LEAD SECRET MISMATCH')
            return jsonify({'ok': False}), 403

        text = ''
        ct = request.headers.get('Content-Type', '') or ''
        if 'application/json' in ct:
            d = request.get_json(silent=True) or {}
            text = (d.get('text') or '').strip()
        else:
            text = (request.form.get('text') or '').strip()

        if not text:
            log('SITE LEAD: empty text')
            return jsonify({'ok': True})

        # Сохраняем заявку с сайта в общий список
        now = time.localtime()
        num = '{:02d}{:02d}-{:02d}{:02d}'.format(now.tm_mday, now.tm_mon, now.tm_hour, now.tm_min)

        name = ''
        phone = ''
        obj = ''
        service = ''
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('Имя:'):
                name = line[4:].strip()
            elif line.startswith('Телефон:'):
                phone = line[8:].strip()
            elif line.startswith('Объект:'):
                obj = line[7:].strip()
            elif line.startswith('Что интересует:'):
                service = line[16:].strip()
            elif line.startswith('Услуга:') and not service:
                service = line[7:].strip()

        lead = {
            'number': num,
            'name': name or 'Заявка с сайта',
            'phone': phone,
            'object': obj,
            'service': service,
            'source': 'site',
            'created_at': int(time.time()),
        }
        data = load_data()
        data['leads'].append(lead)
        data['leads'] = data['leads'][-500:]
        save_data(data)
        log('SITE LEAD SAVED: №' + num + ' ' + name)

        for admin_id in ADMIN_IDS:
            send_message(admin_id, text)

        return jsonify({'ok': True})
    except Exception as e:
        log('SITE LEAD ERROR: ' + str(e))
        return jsonify({'ok': True})


@app.route('/', methods=['GET'])
def index():
    return 'CCTVMOS MAX Bot is running'


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
