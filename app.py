import argparse
import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ==========================================================
# 1. ЭКОНОМИЧЕСКИЕ МОДЕЛИ И ПАРАМЕТРЫ НИШ
# ==========================================================

NICHE_CONFIG: Dict[str, Dict[str, Any]] = {
    "DENTISTRY": {
        "niche_name": "Стоматологическая клиника",
        "niche_genitive": "стоматологий",
        "client_word": "пациент",
        "quality_phrase": "медицинской помощи и врачебной квалификации",
        "benchmark_leads": 70,  # медиана обращений ТОП-3 района
        "base_check": 5500,     # консервативный порог первого визита
        "ltv_months": 12,       # горизонт прикрепления
    },
    "COSMETOLOGY": {
        "niche_name": "Косметологическая клиника",
        "niche_genitive": "клиник косметологии",
        "client_word": "клиент",
        "quality_phrase": "косметологических процедур и сервиса",
        "benchmark_leads": 90,
        "base_check": 4500,
        "ltv_months": 10,
    },
    "BEAUTY_MEDICAL": {
        "niche_name": "Медицинская косметология и эстетика",
        "niche_genitive": "клиник эстетической медицины",
        "client_word": "клиент",
        "quality_phrase": "врачебной косметологии и стандартов безопасности",
        "benchmark_leads": 85,
        "base_check": 4800,
        "ltv_months": 11,
    },
    "GENERAL_MEDICINE": {
        "niche_name": "Многопрофильный медицинский центр",
        "niche_genitive": "медицинских центров",
        "client_word": "пациент",
        "quality_phrase": "лечебной работы и опыта специалистов",
        "benchmark_leads": 120,
        "base_check": 3800,
        "ltv_months": 12,
    },
    "AUTOSERVICES": {
        "niche_name": "Автосервис / Техцентр",
        "niche_genitive": "автосервисов",
        "client_word": "клиент",
        "quality_phrase": "технического обслуживания и ремонта",
        "benchmark_leads": 110,
        "base_check": 7500,
        "ltv_months": 8,
    },
    "HORECA": {
        "niche_name": "Ресторан / Кафе",
        "niche_genitive": "ресторанов",
        "client_word": "гость",
        "quality_phrase": "кухни, гастрономии и атмосферы",
        "benchmark_leads": 250,
        "base_check": 2200,
        "ltv_months": 6,
    },
    "B2B": {
        "niche_name": "B2B / Корпоративные услуги",
        "niche_genitive": "компаний сектора B2B",
        "client_word": "клиент",
        "quality_phrase": "экспертизы, надежности и соблюдения SLA",
        "benchmark_leads": 40,
        "base_check": 35000,
        "ltv_months": 18,
    },
    "RETAIL": {
        "niche_name": "Специализированный ритейл",
        "niche_genitive": "магазинов",
        "client_word": "покупатель",
        "quality_phrase": "ассортимента и уровня обслуживания",
        "benchmark_leads": 180,
        "base_check": 2800,
        "ltv_months": 5,
    },
    "OTHER": {
        "niche_name": "Организация сферы услуг",
        "niche_genitive": "организаций",
        "client_word": "клиент",
        "quality_phrase": "стандартов сервиса и качества работы",
        "benchmark_leads": 80,
        "base_check": 4000,
        "ltv_months": 9,
    },
}

# ==========================================================
# 2. РЕЕСТР КРИТЕРИЕВ СКОРИНГА (ИЗ GOOGLE ТАБЛИЦЫ PIN100)
# Сумма баллов по DENTISTRY ребалансирована ровно в 100.0
# ==========================================================

CRITERIA_REGISTRY: Dict[str, Dict[str, Any]] = {
    "CONT-38.1": {
        "title": "Фото интерьера",
        "group": "Контент и Визуал",
        "complexity": 3,
        "weight_dentistry": 1.5,  # Ребалансировано (-1.0)
        "step": 2,
        "desc_default": "Клиент не видит условий обслуживания. Презентабельный интерьер и аккуратные помещения — маркер качества, без которого доверие падает.",
        "desc_dentistry": "Отсутствие профессиональных фото кабинетов ассоциируется с эконом-сегментом. Пациентам важно заранее увидеть идеальную чистоту, современное оборудование и стерильность."
    },
    "CONT-42.1": {
        "title": "Видео (рилс/тур)",
        "group": "Контент и Визуал",
        "complexity": 3,
        "weight_dentistry": 2.0,
        "step": 2,
        "desc_default": "Видео удерживает внимание пользователя в 3 раза дольше. Без роликов или 3D-туров вы уступаете конкурентам с динамичным контентом.",
        "desc_dentistry": "Видеотуры и ролики о клинике увеличивают время просмотра карточки, что алгоритмы Яндекса считывают как прямой сигнал поведенческого качества."
    },
    "CONV-46.1": {
        "title": "Обложка ручная",
        "group": "Конверсия",
        "complexity": 3,
        "weight_dentistry": 2.0,
        "step": 2,
        "desc_default": "Сгенерированная панорама делает карточку безликой. Вы теряете самый заметный рекламный блок — первый экран карточки.",
        "desc_dentistry": "Кастомная обложка привлекает внимание и сразу транслирует клинический статус. Автоматическая панорама улицы смазывает первое впечатление."
    },
    "CONV-48.1": {
        "title": "Доступность онлайн-записи на приём",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 6.0,
        "step": 1,
        "desc_default": "Отсутствие кнопки быстрой записи отсекает мобильный трафик: клиенты не хотят звонить и сразу уходят к конкурентам с онлайн-виджетом.",
        "desc_dentistry": "В премиальной медицине отсутствие прямой онлайн-записи (МИС) отсекает до 60% вечернего спроса. Пациент с острой болью запишется в один клик к соседям, не дожидаясь утра."
    },
    "CONV-48.2": {
        "title": "Витрина специалистов (врачей / мастеров)",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 5.0,  # Новый внедренный фактор доверия
        "step": 2,
        "desc_default": "Обезличенная карточка снижает конверсию. В сфере услуг клиенты хотят видеть команду до обращения, иначе профиль выглядит безымянным посредником.",
        "desc_dentistry": "В карточке не оцифрованы профили докторов (фото, стаж, специализации). В медицине ключевое решение принимают «на врача»: карточка проигрывает соседям с открытой командой."
    },
    "CONV-49.1": {
        "title": "Уникальное торговое предложение (УТП)",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 4.0,
        "step": 2,
        "desc_default": "Общие фразы без цифр и гарантий не работают: клиент не видит твердых причин выбрать вашу компанию.",
        "desc_dentistry": "Отсутствие сильного медицинского позиционирования (гарантии, технологии, профильные методики) размывает ценность услуг клиники на фоне соседей."
    },
    "CONV-50.1": {
        "title": "Прямой диалог через чат Карт",
        "group": "Конверсия",
        "complexity": 1,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Отключенный чат отсекает огромную долю аудитории, предпочитающей текстовую коммуникацию вместо звонка.",
        "desc_dentistry": "Многие пациенты избегают звонков по телефону в рабочее время. Отключенный чат отсекает обращения на консультацию текстом в один клик."
    },
    "CONV-52.1": {
        "title": "Блок FAQ заполнен",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 1.5,
        "step": 2,
        "desc_default": "Оставшиеся без ответа вопросы заставляют клиента закрыть карточку и уйти к конкуренту с понятными условиями.",
        "desc_dentistry": "Блок 'Вопросы и ответы' закрывает страхи пациентов (болезненность, рассрочки, наркоз) прямо в профиле еще до звонка администратору."
    },
    "CONV-53.1": {
        "title": "Бейджи в витрине",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Без бейджей (Хит, Акция) витрина выглядит монотонной таблицей, а клиент уходит без целевого действия.",
        "desc_dentistry": "Маркетинговые метки на услугах (гигиена, чек-ап, имплантация под ключ) управляют вниманием пациента и ведут его к маржинальным процедурам."
    },
    "GEO-18.4": {
        "title": "Точная точка входа (Маркер двери)",
        "group": "SEO и Трафик",
        "complexity": 5,
        "weight_dentistry": 2.0,
        "step": 3,
        "desc_default": "Навигатор ведет клиента к центру здания или глухому забору, провоцируя раздражение, опоздания и сорванные визиты.",
        "desc_dentistry": "Неточный маркер входа приводит к блужданиям первичных пациентов вокруг здания и срыву плотного графика приема врачей."
    },
    "PROF-01.1": {
        "title": "Название заполнено корректно",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "step": 1,
        "desc_default": "Некорректное или урезанное название мешает нейросети площадки правильно идентифицировать бренд.",
        "desc_dentistry": "Чистое бренд-название обеспечивает корректную защиту брендового поискового трафика в локации."
    },
    "PROF-01.2": {
        "title": "Нет спама в названии",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "step": 1,
        "desc_default": "Переспам ключевыми словами в названии ведет к теневой пессимизации со стороны модерации Яндекса.",
        "desc_dentistry": "Отсутствие поискового спама в заголовке защищает медицинскую организацию от санкций модерации и потери позиций."
    },
    "PROF-03.1": {
        "title": "Основная рубрика заполнена",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "step": 1,
        "desc_default": "Неверная базовая рубрика полностью исключает организацию из тематических категорий поиска.",
        "desc_dentistry": "Корректная базовая медицинская рубрика обеспечивает обязательную привязку к поисковому кластеру района."
    },
    "PROF-03.2": {
        "title": "Полнота охвата смежных рубрик (3+)",
        "group": "SEO и Трафик",
        "complexity": 1.5,
        "weight_dentistry": 1.5,
        "step": 1,
        "desc_default": "Указана только 1 рубрика: незаполненные дополнительные категории срезают до 35% околоцелевого поискового трафика.",
        "desc_dentistry": "Отсутствие смежных рубрик (ортодонтия, детская стоматология, рентгенология) отсекает пациентов со специализированными запросами."
    },
    "PROF-04.1": {
        "title": "Рабочая ссылка на сайт",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Отсутствие сайта лишает бизнес доверия требовательных клиентов, желающих изучить условия детально.",
        "desc_dentistry": "Ссылка на сайт позволяет пациенту изучить лицензии, юридические документы и развернутые кейсы лечения «до/после»."
    },
    "PROF-04.2": {
        "title": "UTM-разметка ссылок",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "step": 1,
        "desc_default": "Без UTM-разметки аналитика слепа: руководство не видит, сколько реальных лидов генерируют Яндекс Карты.",
        "desc_dentistry": "Отсутствие UTM-меток не позволяет руководству оценить реальную окупаемость профиля и долю первичных пациентов с гео-карт."
    },
    "PROF-05.1": {
        "title": "Основной телефон клиники",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Некорректный или отсутствующий телефон обрывает самый прямой канал связи с отделом продаж.",
        "desc_dentistry": "Телефонный контакт должен быть кликабельным и вести на обученного администратора с фиксацией звонков в МИС."
    },
    "PROF-07.1": {
        "title": "Стандартный график работы 7 дней",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Неполный график работы отсекает звонки и визиты клиентов в нерабочие окна.",
        "desc_dentistry": "Пациентам с острой болью критически важно видеть статус работы клиники в выходные и вечерние часы."
    },
    "PROF-08.1": {
        "title": "Базовые атрибуты комфорта",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.5,
        "step": 1,
        "desc_default": "Незаполненные базовые атрибуты (оплата картой, парковка, Wi-Fi) исключают компанию из фильтрации поиска.",
        "desc_dentistry": "Пациенты часто ищут клинику по строгим критериям (наличие парковки, доступность для МГН, безналичная оплата)."
    },
    "PROF-08.2": {
        "title": "Нишевые медицинские атрибуты",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 2.5,
        "step": 1,
        "desc_default": "Проигнорированные нишевые детали приводят к потере клиентов с узкими целевыми запросами.",
        "desc_dentistry": "Пользователи фильтруют клиники по параметрам: «детский прием», «наличие КТ/ОПТГ», «рассрочка». Профиль без них исключается из узкой выдачи."
    },
    "PROF-09.1": {
        "title": "Информативность описания компании",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.5,  # Ребалансировано (-1.0)
        "step": 1,
        "desc_default": "Слишком короткое описание — это потерянная площадь ранжирования: системе не хватает текста для индексации.",
        "desc_dentistry": "Качественный структурированный текст дает Яндексу максимум SEO-сигналов и знакомит пациента с технологиями клиники."
    },
    "PROF-10.3": {
        "title": "Отсутствие перечня услуг в профиле",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 4.0,
        "step": 2,
        "desc_default": "В описании много эмоций, но нет структуры услуг. Клиент не будет додумывать — не найдя нужного, он закроет профиль.",
        "desc_dentistry": "В описании клиники много общих фраз, но нет структуры процедур. Пациент не видит нужного направления и переходит к соседям."
    },
    "PROF-11.1": {
        "title": "Наполненность витрины услуг (10+)",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 4.0,
        "step": 1,
        "desc_default": "Полупустой каталог отталкивает заказчиков, создавая впечатление неполноценного сервиса.",
        "desc_dentistry": "В каталоге заполнено менее трети процедур. Алгоритмы ранжируют выше клиники с полным прейскурантом по всем специализациям."
    },
    "PROF-11.2": {
        "title": "Фото у позиций каталога",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 3.0,
        "step": 1,
        "desc_default": "Покупка вслепую снижает кликабельность: без наглядных фото внимание пользователя рассеивается.",
        "desc_dentistry": "Отсутствие визуализации услуг снижает вовлеченность: качественные фото оборудования и результатов формируют первичное доверие."
    },
    "PROF-11.3": {
        "title": "Цены у товаров и услуг («от...»)",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 3.5,
        "step": 1,
        "desc_default": "Скрытые цены вызывают раздражение: клиент уходит к компаниям с прозрачной открытой стоимостью.",
        "desc_dentistry": "«Слепой» прайс отпугивает пациентов: при высоком чеке люди боятся скрытых накруток в кресле и выбирают клинику с открытыми ценами «от...»."
    },
    "PROF-11.4": {
        "title": "Информативность карточек услуг",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.5,
        "step": 1,
        "desc_default": "Сухие названия без описания не раскрывают ценность продукта и провоцируют сравнение только по цене.",
        "desc_dentistry": "Подробные описания процедур снимают страхи пациента (длительность, материалы, обезболивание) еще до визита."
    },
    "PROF-12.1": {
        "title": "Верификация «Синяя галочка»",
        "group": "Базовое заполнение",
        "complexity": 1.5,
        "weight_dentistry": 1.5,
        "step": 1,
        "desc_default": "Без официального подтверждения профиль лишен приоритетного доверия поисковых алгоритмов.",
        "desc_dentistry": "Синяя галочка подтверждает юридический статус клиники, защищая профиль от несанкционированных правок третьими лицами."
    },
    "PROF-13.1": {
        "title": "Указаны прямые мессенджеры",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.0,
        "step": 1,
        "desc_default": "Отсутствие ссылок на WhatsApp/Telegram отсекает поток лидов, предпочитающих быструю переписку.",
        "desc_dentistry": "Мессенджеры позволяют пациенту быстро отправить снимок для предварительной оценки и записаться без звонка."
    },
    "PROF-15.1": {
        "title": "Юридические данные клиники",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 1.0,  # Ребалансировано (-1.0)
        "step": 1,
        "desc_default": "Отсутствие реквизитов вызывает сомнения в официальной надежности организации.",
        "desc_dentistry": "Заполненные юридические данные и номер лицензии подтверждают правовой статус медицинской организации."
    },
    "REP-27.1": {
        "title": "Базовый порог рейтинга (4.5+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 3,
        "desc_default": "Рейтинг ниже 4.5 отсекает карточку на этапе пользовательских фильтров поиска.",
        "desc_dentistry": "Рейтинг ниже 4.5 критичен для медицины: пациенты боятся доверять здоровье клиникам с низким социальным подтверждением."
    },
    "REP-27.2": {
        "title": "Премиальный уровень рейтинга (4.8+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 3,
        "desc_default": "Рейтинг 4.8+ снимает барьеры недоверия и автоматически ставит карточку в верхние строчки выдачи.",
        "desc_dentistry": "Рейтинг 4.8+ дает максимальную конверсию в районе, снимая 80% возражений пациента еще до первого визита."
    },
    "REP-28.1": {
        "title": "Общий объем базы отзывов (50+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.0,
        "step": 3,
        "desc_default": "Малый массив отзывов не создает эффекта устойчивого социального доказательства.",
        "desc_dentistry": "Большой массив подтвержденных отзывов подтверждает устойчивый многолетний опыт врачебной практики клиники."
    },
    "REP-29.1": {
        "title": "Регулярность свежих отзывов (<14 дней)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.0,
        "step": 2,
        "desc_default": "Отсутствие свежих оценок создает впечатление угасания клиентского потока организации.",
        "desc_dentistry": "Паузы в новых отзывах сигнализируют алгоритмам о спаде спроса и снижают частоту показа клиники в локации."
    },
    "REP-30.1": {
        "title": "Охват базы отзывов ответами (>90%)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.0,
        "step": 2,
        "desc_default": "Игнорирование отзывов показывает равнодушие к сервису после совершения сделки.",
        "desc_dentistry": "Отсутствие регулярных официальных ответов клиники на отзывы разрушает доверие первичных пациентов."
    },
    "REP-30.2": {
        "title": "Оперативность ответов руководства (<=3 дней)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 2,
        "desc_default": "Задержка в ответах на отзывы демонстрирует слабую клиентоориентированность руководства.",
        "desc_dentistry": "В медицине скорость ответа на отзыв воспринимается как показатель внимания клиники к результатам лечения."
    },
    "REP-30.4": {
        "title": "Развернутые ответы руководства (>80 симв.)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 3,
        "desc_default": "Шаблонные отписки из пары слов воспринимаются заказчиками как формальное безразличие.",
        "desc_dentistry": "Персонализированные ответы главврача формируют культуру заботы и насыщают профиль релевантной семантикой."
    },
    "REP-32.2": {
        "title": "Культура диалога с пациентами",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.5,  # Ребалансировано (-2.0)
        "step": 1,
        "desc_default": "Токсичные ответы или открытые споры с клиентами мгновенно уничтожают деловую репутацию.",
        "desc_dentistry": "Первичный пациент выбирает клинику по уровню заботы — оборонительная позиция руководства в отзывах отпугивает семьи к соседям."
    },
    "REP-34.1": {
        "title": "Авторитетность авторов отзывов (Знатоки)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 4.0,
        "step": 3,
        "desc_default": "Отзывы без истории аккаунтов могут пессимизироваться антифрод-фильтрами поисковика.",
        "desc_dentistry": "Оценки авторов со статусом «Знаток города» имеют максимальный вес для ранжирования медицинской карточки."
    },
    "REP-35.1": {
        "title": "Доля отзывов с реальными фото (>10%)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 3,
        "desc_default": "Отзывы без фото вызывают меньше доверия и воспринимаются скептически.",
        "desc_dentistry": "Фотографии пациентов (улыбки, интерьер, врачи) служат самым сильным социальным подтверждением безопасности лечения."
    },
    "SEO-18.3": {
        "title": "Топонимы и ориентиры в тексте",
        "group": "SEO и Трафик",
        "complexity": 4,
        "weight_dentistry": 2.0,
        "step": 3,
        "desc_default": "Без привязки к улицам и метро профиль проигрывает в поиске «рядом со мной».",
        "desc_dentistry": "Названия улиц, станций метро и микрорайона прочно привязывают клинику к локальной поисковой выдаче."
    },
    "SEO-19.2": {
        "title": "Упоминание услуг в тексте отзывов",
        "group": "SEO и Трафик",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "step": 3,
        "desc_default": "Если клиенты не называют услуги, алгоритму не за что зацепиться для предметного ранжирования.",
        "desc_dentistry": "Упоминание процедур (брекеты, импланты, чистка) в текстах отзывов повышает позиции карточки по коммерческим запросам."
    },
}

# ==========================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
# ==========================================================

def format_currency(value: float | int) -> str:
    """Форматирует число с разделением тысяч неразрывным пробелом."""
    return f"{int(round(value)):,}".replace(",", " ")

def get_declension(number: int, word_type: str = "пациент") -> str:
    """Склонение существительных в зависимости от числа."""
    n = abs(int(number)) % 100
    n1 = n % 10
    if word_type == "пациент":
        if 11 <= n <= 19:
            return "пациентов"
        if n1 == 1:
            return "пациент"
        if 2 <= n1 <= 4:
            return "пациента"
        return "пациентов"
    if word_type == "клиент":
        if 11 <= n <= 19:
            return "клиентов"
        if n1 == 1:
            return "клиент"
        if 2 <= n1 <= 4:
            return "клиента"
        return "клиентов"
    return "обращений"

def get_score_color(score: float) -> str:
    """Цветовой маркер общего балла."""
    if score >= 80:
        return "16a34a"  # Зеленый
    if score >= 60:
        return "d97706"  # Оранжевый
    return "dc2626"      # Красный

def sanitize_filename(name: str) -> str:
    """Безопасное имя файла."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")

# ==========================================================
# 4. ГЕНЕРАТОР ПЕРВОГО СООБЩЕНИЯ (ICEBREAKER)
# Утвержденный текст без кассового разрыва и шаблонных фраз
# ==========================================================

def generate_icebreaker(
    title: str,
    rating: float | str,
    competitors: List[str],
    lost_leads: int,
    niche_genitive: str = "стоматологий",
) -> str:
    """Формирует утвержденное сообщение первички для руководителя клиники."""
    if competitors and len(competitors) >= 2:
        comp_str = f"«{competitors[0]}» и «{competitors[1]}»"
    elif competitors and len(competitors) == 1:
        comp_str = f"«{competitors[0]}»"
    else:
        comp_str = "прямые конкуренты"

    low_range = max(1, lost_leads - 2)
    high_range = lost_leads + 3
    leads_range_str = f"{low_range}–{high_range}"

    return (
        f"Добрый день!\n\n"
        f"Анализировали выдачу {niche_genitive} в вашем районе на Яндекс Картах "
        f"и обратили внимание на карточку «{title}». При сильной репутации ({rating}) "
        f"первичный поток прямо сейчас перехватывают {comp_str}.\n\n"
        f"На поверхности лежит отсутствие кнопки быстрой записи (пациенты вечером не хотят звонить "
        f"и уходят к соседям), но алгоритмы пессимизируют карточку еще по нескольким (иногда не очевидным) "
        f"параметрам. По емкости района это отток около {leads_range_str} пациентов в месяц.\n\n"
        f"Собрали наглядный разбор карточки и расчет потерь в короткий PDF на 4 страницы. "
        f"Скинуть файл сюда для ознакомления?"
    )

# ==========================================================
# 5. СКОРИНГ И АВТОМАТИЧЕСКИЙ ОТБОР ТОП-3 ОШИБОК
# ==========================================================

def evaluate_audit_scores(
    raw_scores: Dict[str, float],
    niche: str = "DENTISTRY"
) -> Tuple[float, List[Dict[str, str]]]:
    """
    Рассчитывает финальный балл по 100-балльной шкале и
    автоматически выбирает Топ-3 самые критичные ошибки карточки.
    """
    is_dentistry = (niche == "DENTISTRY")
    total_score = 0.0
    gap_list = []

    for code, meta in CRITERIA_REGISTRY.items():
        max_weight = meta["weight_dentistry"] if is_dentistry else meta.get("weight_default", meta["weight_dentistry"])
        current_score = float(raw_scores.get(code, max_weight))
        current_score = min(max_weight, max(0.0, current_score))
        total_score += current_score

        lost = max_weight - current_score
        if lost > 0.05:
            # Приоритет = Потерянные баллы * (6 - Сложность)
            # Чем проще исправить и больше баллов потеряно, тем выше ошибка
            impact_score = lost * (6.0 - meta["complexity"])
            desc = meta["desc_dentistry"] if is_dentistry else meta["desc_default"]
            gap_list.append({
                "code": code,
                "title": meta["title"],
                "desc": desc,
                "lost": lost,
                "impact": impact_score
            })

    # Сортировка по силе негативного воздействия
    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]

    # Fallback если у карточки нет ошибок
    while len(top_3) < 3:
        top_3.append({
            "code": "GEN-00",
            "title": "Техническая оптимизация карточки",
            "desc": "Карточка оформлена на высоком уровне, рекомендуем поддерживать актуальность прайса и регулярность ответов на отзывы.",
            "lost": 0.0,
            "impact": 0.0
        })

    return round(total_score, 1), top_3

# ==========================================================
# 6. РАСЧЕТ МЕТРИК ОТЧЕТА И ФИНАНСОВЫХ ПОТЕРЬ
# ==========================================================

def calculate_report_metrics(audit_data: Dict[str, Any]) -> Dict[str, str]:
    """Формирует словарь подстановки для Typst-шаблона."""
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_info = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])

    title = audit_data.get("title", "Организация")
    rating = audit_data.get("rating", 4.7)

    # Если передан детальный чеклист баллов, запускаем автоскоринг
    if "criteria_scores" in audit_data:
        score, top_fails = evaluate_audit_scores(audit_data["criteria_scores"], niche_key)
    else:
        score = min(100.0, max(0.0, float(audit_data.get("score", 66.5))))
        top_fails = audit_data.get("top_failures", [])
        if len(top_fails) < 3:
            # Дефолтные выверенные причины
            top_fails = [
                {
                    "title": "Отсутствие кнопки быстрой онлайн-записи (модуля МИС)",
                    "desc": "Пациенты в вечерние часы и с мобильных устройств не могут записаться в один клик. Без прямого действия свыше 60% мобильного трафика возвращаются в выдачу и уходят к конкурентам."
                },
                {
                    "title": "Отсутствие витрины специалистов в профиле",
                    "desc": "В карточке не оцифрованы профили врачей (фотографии, стаж, направления лечения). Пациенты выбирают конкретного доктора: обезличенный профиль клиники уступает соседним карточкам с открытой командой."
                },
                {
                    "title": "Фрагментарный прейскурант без цен формата «от...»",
                    "desc": "В карточке заполнено менее 30% услуг клиники. Алгоритмы Карт пессимизируют профиль по предметным запросам, а пациенты опасаются скрытых накруток в кресле."
                }
            ]

    leads_bench = audit_data.get("benchmark_leads", niche_info["benchmark_leads"])
    base_check = audit_data.get("base_check", niche_info["base_check"])
    ltv_months = audit_data.get("ltv_months", niche_info["ltv_months"])

    # Юнит-экономика потерь
    dev = max(0.0, round(100.0 - score, 1))
    lost_leads = int(round(leads_bench * (dev / 100.0)))
    rev_loss = lost_leads * base_check
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * ltv_months

    word_type = niche_info["client_word"]
    table_declension = get_declension(lost_leads, word_type)

    report_date = audit_data.get(
        "date",
        datetime.date.today().strftime("%d.%m.%Y")
    )

    mapping = {
        "[[TITLE]]": title,
        "[[NICHE]]": niche_info["niche_name"],
        "[[DATE]]": report_date,
        "[[SCORE]]": f"{score:.1f}" if score % 1 != 0 else str(int(score)),
        "[[SCORE_COLOR]]": get_score_color(score),
        "[[REV_LOSS_FMT]]": format_currency(rev_loss),
        "[[CLIENT_LEADS]]": str(leads_bench),
        "[[DEV]]": f"{dev:.1f}" if dev % 1 != 0 else str(int(dev)),
        "[[LOST_LEADS]]": str(lost_leads),
        "[[TABLE_DECLENSION]]": table_declension,
        "[[CLIENT_CHECK_FMT]]": format_currency(base_check),
        "[[CLIENT_LTV]]": str(ltv_months),
        "[[LTV_LOSS_FMT]]": format_currency(ltv_loss),
        "[[QUALITY_PHRASE]]": niche_info["quality_phrase"],
        "[[EXECUTIVE_SUMMARY]]": audit_data.get(
            "executive_summary",
            f"Профиль «{title}» обладает высокой клинической репутацией ({rating}), однако из-за отсутствия прямого конверсионного инструментария (онлайн-запись и открытый прейскурант) алгоритм перенаправляет до {lost_leads} готовых обращений в месяц прямым конкурентам локации."
        ),
        "[[PAGE_3_HEADING]]": "Топ-3 фактора потери пациентов",
        "[[PAGE_3_SUBTITLE]]": "Технические барьеры карточки, снижающие конверсию в первичное обращение:",
        "[[FAIL_1_TITLE]]": top_fails[0]["title"],
        "[[FAIL_1_DESC]]": top_fails[0]["desc"],
        "[[FAIL_2_TITLE]]": top_fails[1]["title"],
        "[[FAIL_2_DESC]]": top_fails[1]["desc"],
        "[[FAIL_3_TITLE]]": top_fails[2]["title"],
        "[[FAIL_3_DESC]]": top_fails[2]["desc"],
        "[[WEEKLY_LOSS_FMT]]": format_currency(weekly_loss),
    }

    return mapping

# ==========================================================
# 7. СБОРКА ТЕМПЛЕЙТА И КОМПИЛЯЦИЯ В TYPST
# ==========================================================

def render_typst_template(template_path: Path, mapping: Dict[str, str]) -> str:
    """Подставляет расчетные значения в Typst-шаблон."""
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()

    for placeholder, val in mapping.items():
        content = content.replace(placeholder, str(val))

    return content

def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> bool:
    """Компилирует Typst код в готовый PDF файл."""
    temp_typ_path = work_dir / f"temp_{output_pdf_path.stem}.typ"

    try:
        with open(temp_typ_path, "w", encoding="utf-8") as f:
            f.write(typst_content)

        cmd = ["typst", "compile", str(temp_typ_path), str(output_pdf_path)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка компиляции Typst: {e.stderr}")
        return False
    except FileNotFoundError:
        print("Ошибка: Typst CLI не найден в PATH системы.")
        return False
    finally:
        if temp_typ_path.exists():
            try:
                temp_typ_path.unlink()
            except OSError:
                pass

# ==========================================================
# 8. ПАЙПЛАЙН ГЕНЕРАЦИИ АУДИТА
# ==========================================================

def process_clinic_audit(
    audit_data: Dict[str, Any],
    template_path: Path,
    output_dir: Path
) -> Tuple[Optional[Path], Path]:
    """
    Генерирует связку:
    1. 4-страничный PDF-отчет упущенной выручки
    2. Персонализированный Icebreaker для ЛПР
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    title = audit_data.get("title", "Организация")
    org_id = audit_data.get("org_id", "0000000000")
    date_str = audit_data.get("date_raw", datetime.date.today().strftime("%Y-%m-%d"))

    file_prefix = f"{sanitize_filename(title)}_{org_id}_{date_str}"
    pdf_path = output_dir / f"{file_prefix}_report.pdf"
    txt_path = output_dir / f"{file_prefix}_icebreaker.txt"

    mapping = calculate_report_metrics(audit_data)

    # Генерация Typst PDF
    rendered_typst = render_typst_template(template_path, mapping)
    success = compile_typst_pdf(rendered_typst, pdf_path, work_dir=output_dir)
    if success:
        print(f"[+] Сгенерирован PDF отчет: {pdf_path.resolve()}")
    else:
        print(f"[-] Не удалось собрать PDF для {title}")
        pdf_path = None

    # Генерация первого касания
    niche_key = audit_data.get("niche", "DENTISTRY")
    niche_genitive = NICHE_CONFIG.get(niche_key, NICHE_CONFIG["DENTISTRY"])["niche_genitive"]
    lost_leads_int = int(mapping["[[LOST_LEADS]]"])

    icebreaker_text = generate_icebreaker(
        title=title,
        rating=audit_data.get("rating", 4.7),
        competitors=audit_data.get("competitors", []),
        lost_leads=lost_leads_int,
        niche_genitive=niche_genitive,
    )

    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(icebreaker_text)

    print(f"[+] Сохранен текст первого сообщения: {txt_path.resolve()}")
    return pdf_path, txt_path

# ==========================================================
# 9. ТОЧКА ВХОДА CLI
# ==========================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="PIN100 Analytics: Промышленный генератор аудитов и icebreaker-сообщений."
    )
    parser.add_argument(
        "-f", "--file", type=str, help="Путь к JSON-файлу с аудитом клиники или списком клиник."
    )
    parser.add_argument(
        "-t", "--template", type=str, default="report_template.typ",
        help="Путь к шаблону Typst (по умолчанию: report_template.typ)."
    )
    parser.add_argument(
        "-o", "--outdir", type=str, default="output",
        help="Директория для сохранения готовых файлов (по умолчанию: ./output)."
    )
    parser.add_argument(
        "--sample", action="store_true",
        help="Запустить демонстрационный расчет для тестовой клиники «Айдента»."
    )

    args = parser.parse_args()
    template_file = Path(args.template)

    if not template_file.exists():
        print(f"Ошибка: Файл шаблона '{template_file}' не найден рядом со скриптом.")
        return

    output_dir = Path(args.outdir)

    if args.sample or not args.file:
        sample_data = {
            "title": "Айдента",
            "org_id": "1015646715",
            "date": "11.09.2026",
            "date_raw": "2026-09-11",
            "rating": 4.7,
            "niche": "DENTISTRY",
            "competitors": ["РозДент", "На Приморской"],
            "benchmark_leads": 70,
            "base_check": 5500,
            "ltv_months": 12,
            # Детальный срез чеклиста из Google Таблицы (демонстрация скоринга):
            "criteria_scores": {
                "CONV-48.1": 0.0,  # Нет кнопки онлайн-записи (потеряно 6.0 баллов)
                "CONV-48.2": 0.0,  # Нет витрины врачей (потеряно 5.0 баллов)
                "PROF-11.3": 0.0,  # Нет цен "от..." (потеряно 3.5 балла)
                "PROF-10.3": 0.0,  # Нет структуры услуг (потеряно 4.0 балла)
                "REP-30.1": 1.0,   # Слабый охват ответами (потеряно 2.0 балла)
                "CONT-38.1": 0.5,  # Мало фото кабинетов (потерян 1.0 балл)
                # Все остальные параметры клиника выполняет на максимум
            }
        }
        process_clinic_audit(sample_data, template_file, output_dir)
    else:
        audit_file = Path(args.file)
        if not audit_file.exists():
            print(f"Ошибка: Входной файл '{audit_file}' не найден.")
            return

        with open(audit_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            for entry in data:
                process_clinic_audit(entry, template_file, output_dir)
        else:
            process_clinic_audit(data, template_file, output_dir)

if __name__ == "__main__":
    main()
