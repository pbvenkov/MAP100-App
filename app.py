import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st

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
        "weight_dentistry": 1.5,
        "desc_default": "Клиент не видит условий обслуживания. Презентабельный интерьер — ключевой маркер качества, без которого доверие падает.",
        "desc_dentistry": "Отсутствие профессиональных фото кабинетов ассоциируется с клиникой эконом-класса. Пациентам важно заранее увидеть стерильность и оборудование."
    },
    "CONT-42.1": {
        "title": "Видео (рилс/тур)",
        "group": "Контент и Визуал",
        "complexity": 3,
        "weight_dentistry": 2.0,
        "desc_default": "Видео удерживает внимание в 3 раза дольше. Без роликов или туров вы уступаете конкурентам с динамичным контентом.",
        "desc_dentistry": "Видеотуры увеличивают время просмотра карточки, что алгоритмы Яндекса считывают как прямой сигнал качества профиля."
    },
    "CONV-46.1": {
        "title": "Обложка ручная",
        "group": "Конверсия",
        "complexity": 3,
        "weight_dentistry": 2.0,
        "desc_default": "Стандартная сгенерированная панорама улицы делает карточку безликой. Теряется первый экран профиля.",
        "desc_dentistry": "Кастомная обложка клиники привлекает внимание и сразу транслирует клинический статус. Авто-панорама улицы смазывает первое впечатление."
    },
    "CONV-48.1": {
        "title": "Доступность онлайн-записи на приём",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 6.0,
        "desc_default": "Отсутствие виджета записи отсекает горячий трафик: клиент не хочет звонить и уходит к конкурентам с кнопкой записи.",
        "desc_dentistry": "В современной медицине отсутствие онлайн-записи (МИС) отсекает до 60% вечернего спроса. Пациент с острой болью запишется в один клик к соседям, не дожидаясь утра."
    },
    "CONV-48.2": {
        "title": "Витрина специалистов (врачей / мастеров)",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 5.0,
        "desc_default": "Обезличенная карточка снижает доверие. Без блока специалистов профиль выглядит безымянным посредником.",
        "desc_dentistry": "В карточке не оцифрованы профили врачей (фотографии, стаж, специализации). В медицине выбор делают «на врача»: обезличенный профиль проигрывает соседям с открытой командой."
    },
    "CONV-49.1": {
        "title": "Уникальное торговое предложение (УТП)",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 4.0,
        "desc_default": "Общие фразы без цифр и гарантий не работают: клиент не видит причин выбрать именно вас.",
        "desc_dentistry": "Отсутствие твердого позиционирования в описании (гарантии, профильные методики) размывает ценность услуг клиники."
    },
    "CONV-50.1": {
        "title": "Прямой диалог через чат Карт",
        "group": "Конверсия",
        "complexity": 1,
        "weight_dentistry": 2.0,
        "desc_default": "Отключенный чат отсекает пользователей, предпочитающих текстовую коммуникацию вместо прямого звонка.",
        "desc_dentistry": "Многие пациенты избегают звонков по телефону в рабочее время. Отключенный чат отсекает аудиторию, готовую записаться текстом."
    },
    "CONV-52.1": {
        "title": "Блок FAQ заполнен",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 1.5,
        "desc_default": "Оставшиеся без ответа вопросы заставляют клиента уйти к конкуренту с понятными условиями.",
        "desc_dentistry": "Блок 'Вопросы и ответы' закрывает страхи пациентов (болезненность, рассрочка, гарантии) прямо в профиле еще до звонка."
    },
    "CONV-53.1": {
        "title": "Бейджи в витрине",
        "group": "Конверсия",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "desc_default": "Без маркетинговых бейджей витрина выглядит монотонной таблицей, снижая число кликов по товарам.",
        "desc_dentistry": "Маркетинговые метки на ключевых услугах (гигиена, чек-ап, имплантация) управляют вниманием пациента и ведут к маржинальным процедурам."
    },
    "GEO-18.4": {
        "title": "Точная точка входа (Маркер двери)",
        "group": "SEO и Трафик",
        "complexity": 5,
        "weight_dentistry": 2.0,
        "desc_default": "Навигатор ведет клиентов к глухому забору, провоцируя опоздания и отказы от визита.",
        "desc_dentistry": "Неточный маркер входа приводит к блужданиям первичных пациентов вокруг здания и срыву плотного графика приема врачей."
    },
    "PROF-01.1": {
        "title": "Название заполнено корректно",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "desc_default": "Некорректное название снижает базовое доверие алгоритмов поисковой системы.",
        "desc_dentistry": "Чистое бренд-название обеспечивает корректную защиту брендового поискового трафика клиники."
    },
    "PROF-01.2": {
        "title": "Нет спама в названии",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "desc_default": "Вшивание ключевых слов в название ведет к теневому бану и пессимизации модерацией Яндекса.",
        "desc_dentistry": "Отсутствие поискового спама в названии защищает карточку клиники от санкций и резкой потери позиций."
    },
    "PROF-03.1": {
        "title": "Основная рубрика заполнена",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "desc_default": "Неверная рубрика полностью исключает организацию из тематических категорий поиска.",
        "desc_dentistry": "Корректная базовая медицинская рубрика обеспечивает обязательную привязку к поисковому кластеру района."
    },
    "PROF-03.2": {
        "title": "Полнота охвата смежных рубрик (3+)",
        "group": "SEO и Трафик",
        "complexity": 1.5,
        "weight_dentistry": 1.5,
        "desc_default": "Указана только одна рубрика: незаполненные категории срезают до 35% трафика по сопутствующим услугам.",
        "desc_dentistry": "Отсутствие смежных рубрик (ортодонтия, детская стоматология, рентгенология) отсекает пациентов с узкими запросами."
    },
    "PROF-04.1": {
        "title": "Рабочая ссылка на сайт",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "desc_default": "Отсутствие ссылки на сайт лишает бизнес статуса в глазах требовательных клиентов.",
        "desc_dentistry": "Ссылка на сайт позволяет пациенту изучить лицензии, медицинские протоколы и развернутые кейсы лечения «до/после»."
    },
    "PROF-04.2": {
        "title": "UTM-разметка ссылок",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 1.0,
        "desc_default": "Без разметки ссылок аналитика слепа: руководство не видит реальной отдачи от гео-трафика.",
        "desc_dentistry": "Отсутствие UTM-меток не позволяет руководству оценить реальную окупаемость профиля и поток первичных пациентов."
    },
    "PROF-05.1": {
        "title": "Основной телефон клиники",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "desc_default": "Карточка без телефона обрывает самый горячий и прямой канал продаж.",
        "desc_dentistry": "Телефон клиники должен быть кликабельным и вести на обученного администратора с фиксацией в МИС."
    },
    "PROF-07.1": {
        "title": "Стандартный график работы 7 дней",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 2.0,
        "desc_default": "Неполный график работы отсекает звонки и визиты заказчиков в спорные временные интервалы.",
        "desc_dentistry": "Пациентам с острой болью критически важно видеть статус работы клиники в выходные и вечерние часы."
    },
    "PROF-08.1": {
        "title": "Базовые атрибуты комфорта",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 1.5,
        "desc_default": "Незаполненные «Особенности» исключают вас из выдачи с жесткими пользовательскими фильтрами.",
        "desc_dentistry": "Пациенты часто фильтруют клиники по удобствам (парковка, доступность для МГН, оплата картой)."
    },
    "PROF-08.2": {
        "title": "Нишевые медицинские атрибуты",
        "group": "SEO и Трафик",
        "complexity": 1,
        "weight_dentistry": 2.5,
        "desc_default": "Проигнорированные нишевые атрибуты отдают клиентов с точными запросами конкурентам.",
        "desc_dentistry": "Пользователи фильтруют клиники: «детский прием», «КТ/ОПТГ», «рассрочка». Без них карточка исключается из выдачи."
    },
    "PROF-09.1": {
        "title": "Информативность описания компании",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.5,
        "desc_default": "Слишком короткое описание — это потерянная площадь ранжирования: системе не хватает текста для индексации.",
        "desc_dentistry": "Качественный структурированный текст дает Яндексу максимум SEO-сигналов и знакомит пациента со стандартами лечения."
    },
    "PROF-10.3": {
        "title": "Отсутствие перечня услуг в профиле",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 4.0,
        "desc_default": "В описании много эмоций, но нет структуры услуг. Клиент не будет додумывать и закроет карточку.",
        "desc_dentistry": "В описании клиники много общих фраз, но нет структуры процедур. Пациент не видит нужного направления и переходит к соседям."
    },
    "PROF-11.1": {
        "title": "Наполненность витрины услуг (10+)",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 4.0,
        "desc_default": "Полупустой каталог услуг отталкивает заказчиков, создавая образ неполноценного сервиса.",
        "desc_dentistry": "В каталоге заполнено менее трети процедур. Алгоритмы ранжируют выше клиники с оцифрованным прейскурантом."
    },
    "PROF-11.2": {
        "title": "Фото у позиций каталога",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 3.0,
        "desc_default": "Покупка вслепую снижает конверсию: без наглядных фото внимание клиента рассеивается.",
        "desc_dentistry": "Отсутствие визуализации услуг снижает доверие: качественные фото оборудования и процедур повышают кликабельность."
    },
    "PROF-11.3": {
        "title": "Цены у товаров и услуг («от...»)",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 3.5,
        "desc_default": "Скрытые цены вызывают подозрение: большинство пользователей выбирают карточки с открытым прайсом.",
        "desc_dentistry": "«Слепой» прайс отпугивает пациентов: при высоком чеке люди боятся скрытых накруток в кресле и выбирают клинику с ценами «от...»."
    },
    "PROF-11.4": {
        "title": "Информативность карточек услуг",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.5,
        "desc_default": "Сухие названия без описаний не раскрывают ценность продукта и ведут к ценовому демпингу.",
        "desc_dentistry": "Подробные описания медицинских услуг снимают страхи пациента (материалы, гарантия, анестезия) еще до визита."
    },
    "PROF-12.1": {
        "title": "Верификация «Синяя галочка»",
        "group": "Базовое заполнение",
        "complexity": 1.5,
        "weight_dentistry": 1.5,
        "desc_default": "Без официальной верификации профиль теряет доверие площадки и не может бороться за ТОП.",
        "desc_dentistry": "Синяя галочка подтверждает официальный статус клиники, защищая профиль от несанкционированных правок третьими лицами."
    },
    "PROF-13.1": {
        "title": "Указаны прямые мессенджеры",
        "group": "Базовое заполнение",
        "complexity": 1,
        "weight_dentistry": 2.0,
        "desc_default": "Отсутствие ссылок на мессенджеры отсекает клиентов, предпочитающих быструю переписку звонкам.",
        "desc_dentistry": "Мессенджеры позволяют пациенту быстро отправить снимок для предварительной оценки и записаться без звонка."
    },
    "PROF-15.1": {
        "title": "Юридические данные клиники",
        "group": "Базовое заполнение",
        "complexity": 2,
        "weight_dentistry": 1.0,
        "desc_default": "Отсутствие реквизитов вызывает сомнения в официальной надежности организации.",
        "desc_dentistry": "Заполненные реквизиты и номер медицинской лицензии подтверждают правовой статус организации."
    },
    "REP-27.1": {
        "title": "Базовый порог рейтинга (4.5+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Рейтинг ниже 4.5 — критическая зона: карточка отсекается большинством фильтров поиска.",
        "desc_dentistry": "Рейтинг ниже 4.5 критичен для медицины: пациенты опасаются доверять здоровье клиникам с низкими оценками."
    },
    "REP-27.2": {
        "title": "Премиальный уровень рейтинга (4.8+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Рейтинг 4.8+ ставит карточку в топ выдачи и автоматически снимает большинство возражений.",
        "desc_dentistry": "Рейтинг 4.8+ обеспечивает максимальную конверсию, снимая 80% возражений пациента еще до первого звонка."
    },
    "REP-28.1": {
        "title": "Общий объем базы отзывов (50+)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.0,
        "desc_default": "Малый массив отзывов не создает устойчивого социального доказательства надежности бизнеса.",
        "desc_dentistry": "Большой массив подтвержденных отзывов доказывает многолетний опыт успешной клинической практики."
    },
    "REP-29.1": {
        "title": "Регулярность свежих отзывов (<14 дней)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.0,
        "desc_default": "Отсутствие свежих оценок создает впечатление угасания клиентской активности компании.",
        "desc_dentistry": "Паузы в новых отзывах сигнализируют поисковым алгоритмам о спаде спроса и снижают органическую видимость."
    },
    "REP-30.1": {
        "title": "Охват базы отзывов ответами (>90%)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.0,
        "desc_default": "Игнорирование отзывов показывает равнодушие руководства к клиентам после получения оплаты.",
        "desc_dentistry": "Отсутствие регулярных официальных ответов клиники на отзывы разрушает первичное доверие пациентов."
    },
    "REP-30.2": {
        "title": "Оперативность ответов руководства (<=3 дней)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Задержка в ответах на отзывы демонстрирует низкую вовлеченность клиентского сервиса.",
        "desc_dentistry": "В медицине задержка ответа на отзыв воспринимается как невнимание к результатам проведенного лечения."
    },
    "REP-30.4": {
        "title": "Развернутые ответы руководства (>80 симв.)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Шаблонные отписки из двух слов считываются клиентами как формальное безразличие.",
        "desc_dentistry": "Персонализированные ответы главврача формируют культуру заботы и естественно насыщают карточку поисковыми запросами."
    },
    "REP-32.2": {
        "title": "Культура диалога с пациентами",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 3.5,
        "desc_default": "Токсичные ответы или споры в публичном поле разрушают репутацию организации.",
        "desc_dentistry": "Первичный пациент выбирает клинику по уровню заботы — оборонительная позиция руководства в отзывах отпугивает семьи к соседям."
    },
    "REP-34.1": {
        "title": "Авторитетность авторов отзывов (Знатоки)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 4.0,
        "desc_default": "Отзывы пустых аккаунтов без истории могут пессимизироваться спам-фильтрами площадки.",
        "desc_dentistry": "Оценки авторов со статусом «Знаток города» имеют приоритетный вес для ранжирования медицинской карточки."
    },
    "REP-35.1": {
        "title": "Доля отзывов с реальными фото (>10%)",
        "group": "Репутация",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Отзывы без фотографий вызывают меньше доверия и воспринимаются скептически.",
        "desc_dentistry": "Фотографии реальных пациентов служат сильнейшим социальным подтверждением комфорта и безопасности лечения."
    },
    "SEO-18.3": {
        "title": "Топонимы и ориентиры в тексте",
        "group": "SEO и Трафик",
        "complexity": 4,
        "weight_dentistry": 2.0,
        "desc_default": "Без привязки к улицам и метро профиль проигрывает в выдаче по запросам «рядом со мной».",
        "desc_dentistry": "Названия станций метро, улиц и микрорайона прочно закрепляют клинику за локальной поисковой выдачей."
    },
    "SEO-19.2": {
        "title": "Упоминание услуг в тексте отзывов",
        "group": "SEO и Трафик",
        "complexity": 4,
        "weight_dentistry": 2.5,
        "desc_default": "Если клиенты не упоминают конкретные услуги, алгоритму не за что зацепиться для ранжирования.",
        "desc_dentistry": "Упоминание процедур (имплантация, брекеты, гигиена) в отзывах пациентов повышает позиции клиники в предметном поиске."
    },
}

# ==========================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ И СКЛОНЕНИЯ
# ==========================================================

def format_currency(value: float | int) -> str:
    """Форматирует число с разделением тысяч неразрывным пробелом."""
    return f"{int(round(value)):,}".replace(",", " ")

def get_declension(number: int, word_type: str = "пациент") -> str:
    """Корректное склонение существительных в зависимости от числа."""
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
    """Безопасное имя файла без спецсимволов."""
    return re.sub(r'[\\/*?:"<>| ]', "_", name).strip("_")

# ==========================================================
# 4. ГЕНЕРАТОР ПЕРВОГО СООБЩЕНИЯ (ICEBREAKER)
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
    автоматически отбирает Топ-3 самые критичные ошибки карточки.
    """
    is_dentistry = (niche == "DENTISTRY")
    total_score = 0.0
    gap_list = []

    for code, meta in CRITERIA_REGISTRY.items():
        max_weight = meta["weight_dentistry"]
        current_score = float(raw_scores.get(code, max_weight))
        current_score = min(max_weight, max(0.0, current_score))
        total_score += current_score

        lost = max_weight - current_score
        if lost > 0.05:
            # Сила негативного влияния = Потерянные баллы * (6 - Сложность)
            impact_score = lost * (6.0 - meta["complexity"])
            desc = meta["desc_dentistry"] if is_dentistry else meta["desc_default"]
            gap_list.append({
                "code": code,
                "title": meta["title"],
                "desc": desc,
                "lost": lost,
                "impact": impact_score
            })

    gap_list.sort(key=lambda x: x["impact"], reverse=True)
    top_3 = gap_list[:3]

    while len(top_3) < 3:
        top_3.append({
            "code": "GEN-00",
            "title": "Техническая оптимизация карточки",
            "desc": "Карточка оформлена на высоком уровне. Рекомендуем поддерживать актуальность цен и регулярность ответов на отзывы.",
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

    if "criteria_scores" in audit_data:
        score, top_fails = evaluate_audit_scores(audit_data["criteria_scores"], niche_key)
    else:
        score = min(100.0, max(0.0, float(audit_data.get("score", 66.5))))
        top_fails = audit_data.get("top_failures", [])
        if len(top_fails) < 3:
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

    dev = max(0.0, round(100.0 - score, 1))
    lost_leads = int(round(leads_bench * (dev / 100.0)))
    rev_loss = lost_leads * base_check
    weekly_loss = int(round(rev_loss / 4.33))
    ltv_loss = rev_loss * ltv_months

    word_type = niche_info["client_word"]
    table_declension = get_declension(lost_leads, word_type)
    report_date = audit_data.get("date", datetime.date.today().strftime("%d.%m.%Y"))

    return {
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

def compile_typst_pdf(typst_content: str, output_pdf_path: Path, work_dir: Path) -> Tuple[bool, str]:
    """Компилирует Typst код в готовый PDF файл."""
    temp_typ_path = work_dir / f"temp_{output_pdf_path.stem}.typ"
    try:
        with open(temp_typ_path, "w", encoding="utf-8") as f:
            f.write(typst_content)

        cmd = ["typst", "compile", str(temp_typ_path), str(output_pdf_path)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, ""
    except subprocess.CalledProcessError as e:
        return False, f"Ошибка Typst: {e.stderr}"
    except FileNotFoundError:
        return False, "Утилита 'typst' CLI не установлена в PATH."
    finally:
        if temp_typ_path.exists():
            try:
                temp_typ_path.unlink()
            except OSError:
                pass

# ==========================================================
# 8. STREAMLIT ВЕБ-ИНТЕРФЕЙС
# ==========================================================

def run_streamlit_app() -> None:
    st.set_page_config(
        page_title="PIN100 Analytics",
        page_icon="📍",
        layout="wide"
    )

    st.title("📍 PIN100 Analytics: Аудит гео-выдачи клиник")
    st.caption("Автоматический расчет перетока пациентов к конкурентам, генератор 4-страничного PDF и первого сообщения ЛПР.")

    # Дефолтный чеклист для «Айдента» (дает ~66.5 баллов)
    default_scores = {
        "CONV-48.1": 0.0,  # Нет кнопки онлайн-записи (-6.0)
        "CONV-48.2": 0.0,  # Нет витрины врачей (-5.0)
        "PROF-10.3": 0.0,  # Нет структуры услуг в профиле (-4.0)
        "PROF-11.3": 0.0,  # Нет цен "от..." (-3.5)
        "REP-30.1": 1.0,   # Охват ответами слабее бенчмарка (-2.0)
        "CONT-38.1": 0.5,  # Мало фото кабинетов (-1.0)
    }

    if "criteria_scores" not in st.session_state:
        st.session_state.criteria_scores = {}
        for code, meta in CRITERIA_REGISTRY.items():
            max_w = meta["weight_dentistry"]
            st.session_state.criteria_scores[code] = default_scores.get(code, max_w)

    with st.sidebar:
        st.header("1. Параметры карточки")
        title = st.text_input("Название клиники", value="Айдента")
        org_id = st.text_input("ID в Яндекс Бизнесе", value="1015646715")
        niche_key = st.selectbox(
            "Направление бизнеса",
            options=list(NICHE_CONFIG.keys()),
            format_func=lambda x: NICHE_CONFIG[x]["niche_name"]
        )
        rating = st.number_input("Текущий рейтинг карточки", min_value=1.0, max_value=5.0, value=4.7, step=0.1)

        st.header("2. Конкуренты района")
        comp_1 = st.text_input("Конкурент №1", value="РозДент")
        comp_2 = st.text_input("Конкурент №2", value="На Приморской")

        st.header("3. Экономика локации")
        niche_defaults = NICHE_CONFIG[niche_key]
        leads_bench = st.number_input("Медиана ТОП-3 (обращений/мес)", value=niche_defaults["benchmark_leads"], step=5)
        base_check = st.number_input("Базовый чек первого приема (₽)", value=niche_defaults["base_check"], step=500)
        ltv_months = st.number_input("Горизонт прикрепления (мес)", value=niche_defaults["ltv_months"], step=1)

    # Вычисление баллов и Топ-3
    calculated_score, top_failures = evaluate_audit_scores(st.session_state.criteria_scores, niche_key)

    audit_payload = {
        "title": title,
        "org_id": org_id,
        "date": datetime.date.today().strftime("%d.%m.%Y"),
        "date_raw": datetime.date.today().strftime("%Y-%m-%d"),
        "rating": rating,
        "score": calculated_score,
        "niche": niche_key,
        "competitors": [c.strip() for c in [comp_1, comp_2] if c.strip()],
        "benchmark_leads": leads_bench,
        "base_check": base_check,
        "ltv_months": ltv_months,
        "top_failures": top_failures,
    }

    mapping = calculate_report_metrics(audit_payload)

    tab_summary, tab_icebreaker, tab_checklist = st.tabs([
        "📊 Результаты и Юнит-экономика",
        "✉️ Первое сообщение (Icebreaker)",
        "📋 Чек-лист аудита (41 критерий)",
    ])

    with tab_summary:
        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        col_m1.metric("Готовность профиля", f"{mapping['[[SCORE]]']} / 100")
        col_m2.metric("Потери пациентов", f"~{mapping['[[LOST_LEADS]]']} чел/мес")
        col_m3.metric("Упущенная выручка", f"{mapping['[[REV_LOSS_FMT]]']} ₽/мес")
        col_m4.metric("Потери за неделю", f"~{mapping['[[WEEKLY_LOSS_FMT]]']} ₽/нед")

        st.divider()

        st.subheader("Автоматический Топ-3 барьеров (Стр. 3 отчета)")
        for idx, fail in enumerate(top_failures, start=1):
            st.markdown(f"**{idx}. {fail['title']}**")
            st.caption(fail["desc"])

        st.divider()

        # Блок генерации PDF
        template_file = Path("report_template.typ")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        file_prefix = f"{sanitize_filename(title)}_{org_id}_{audit_payload['date_raw']}"
        pdf_path = output_dir / f"{file_prefix}_report.pdf"

        if not template_file.exists():
            st.error("Файл 'report_template.typ' не найден в корне проекта. Поместите шаблон рядом с app.py.")
        else:
            if st.button("🚀 Скомпилировать PDF-отчет", type="primary", use_container_width=True):
                rendered_typst = render_typst_template(template_file, mapping)
                ok, err = compile_typst_pdf(rendered_typst, pdf_path, output_dir)
                if ok:
                    st.success(f"PDF отчет успешно собран: {pdf_path.name}")
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            label="📥 Скачать готовый PDF отчет",
                            data=f.read(),
                            file_name=pdf_path.name,
                            mime="application/pdf",
                            use_container_width=True
                        )
                else:
                    st.warning(f"{err}\n\nВы можете скачать готовый файл разметки Typst для локальной компиляции:")
                    st.download_button(
                        label="📥 Скачать файл report.typ",
                        data=rendered_typst,
                        file_name=f"{file_prefix}.typ",
                        mime="text/plain",
                        use_container_width=True
                    )

    with tab_icebreaker:
        st.subheader("Утвержденный текст первого касания")
        st.caption("Фокус на перехвате пациентов соседями, без спам-шаблонов и без слова «кассовый разрыв».")

        lost_leads_int = int(mapping["[[LOST_LEADS]]"])
        icebreaker_txt = generate_icebreaker(
            title=title,
            rating=rating,
            competitors=audit_payload["competitors"],
            lost_leads=lost_leads_int,
            niche_genitive=niche_defaults["niche_genitive"]
        )

        st.text_area("Текст для WhatsApp / Telegram / Email", value=icebreaker_txt, height=220)
        st.download_button(
            label="Сохранить текст в .txt",
            data=icebreaker_txt,
            file_name=f"{file_prefix}_icebreaker.txt",
            mime="text/plain"
        )

    with tab_checklist:
        st.subheader("Интерактивный скоринг по Google Таблице PIN100")
        st.caption("Измените баллы критериев — итоговый скор, финансовые потери и Топ-3 ошибок пересчитаются автоматически.")

        groups = {}
        for code, meta in CRITERIA_REGISTRY.items():
            g = meta["group"]
            groups.setdefault(g, []).append((code, meta))

        for grp_name, items in groups.items():
            with st.expander(f"{grp_name} ({len(items)} критериев)", expanded=(grp_name == "Конверсия")):
                for code, meta in items:
                    max_val = meta["weight_dentistry"]
                    current_val = float(st.session_state.criteria_scores.get(code, max_val))
                    val = st.slider(
                        f"[{code}] {meta['title']} (макс: {max_val} б.)",
                        min_value=0.0,
                        max_value=float(max_val),
                        value=current_val,
                        step=0.5 if max_val >= 2 else 0.25,
                        key=f"slider_{code}"
                    )
                    st.session_state.criteria_scores[code] = val

# ==========================================================
# 9. ТОЧКА ВХОДА (ДВОЙНОЙ РЕЖИМ: STREAMLIT + CLI)
# ==========================================================

if __name__ == "__main__":
    # Если запуск с флагом CLI из терминала
    if "--cli" in sys.argv:
        print("[+] Запуск в CLI режиме...")
        sample_scores = {
            "CONV-48.1": 0.0,
            "CONV-48.2": 0.0,
            "PROF-10.3": 0.0,
            "PROF-11.3": 0.0,
            "REP-30.1": 1.0,
            "CONT-38.1": 0.5,
        }
        score, top_3 = evaluate_audit_scores(sample_scores, "DENTISTRY")
        sample_audit = {
            "title": "Айдента",
            "org_id": "1015646715",
            "date": "11.09.2026",
            "date_raw": "2026-09-11",
            "rating": 4.7,
            "score": score,
            "niche": "DENTISTRY",
            "competitors": ["РозДент", "На Приморской"],
            "benchmark_leads": 70,
            "base_check": 5500,
            "ltv_months": 12,
            "top_failures": top_3,
        }
        output_path = Path("output")
        output_path.mkdir(exist_ok=True)
        t_file = Path("report_template.typ")
        if t_file.exists():
            mapping = calculate_report_metrics(sample_audit)
            rendered = render_typst_template(t_file, mapping)
            pdf_p = output_path / "Айдента_sample_report.pdf"
            compile_typst_pdf(rendered, pdf_p, output_path)
            print(f"[+] PDF сохранен в {pdf_p}")
    else:
        # Стандартный запуск через Streamlit сервер
        run_streamlit_app()
