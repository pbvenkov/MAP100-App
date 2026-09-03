NICHE_LEXICON = {
    "DENTISTRY": {
        "profile": "стоматологической клиники",
        "clients": "пациентов",
        "capacity": "к вашим креслам",
        "asset": "врачебной экспертизой и сильной практикой"
    },
    "BEAUTY_MEDICAL": {
        "profile": "медицинского центра",
        "clients": "пациентов",
        "capacity": "к записям на прием",
        "asset": "высоким уровнем сервиса и квалификацией специалистов"
    },
    "HORECA": {
        "profile": "ресторана / заведения",
        "clients": "гостей",
        "capacity": "к бронированию столиков",
        "asset": "кухней, атмосферой и стабильным качеством"
    },
    "AUTO": {
        "profile": "автотехцентра",
        "clients": "автовладельцев",
        "capacity": "к постам обслуживания и подъемникам",
        "asset": "экспертностью мастеров и качеством работ"
    },
    "EDUCATION": {
        "profile": "образовательного центра",
        "clients": "учеников и родителей",
        "capacity": "к наборам в учебные группы",
        "asset": "педагогическим составом и методикой обучения"
    },
    "RETAIL": {
        "profile": "торговой компании",
        "clients": "покупателей",
        "capacity": "к вашей торговой витрине",
        "asset": "широким ассортиментом и конкурентными условиями"
    },
    "B2B": {
        "profile": "компании",
        "clients": "корпоративных клиентов",
        "capacity": "к диалогу с отделом продаж",
        "asset": "надежностью поставок и экспертным подходом"
    },
    "B2B_HEAVY": {
        "profile": "производственного предприятия",
        "clients": "заказчиков",
        "capacity": "к загрузке производственных линий",
        "asset": "технической базой и контролем качества"
    },
    "SERVICES": {
        "profile": "сервисной компании",
        "clients": "клиентов",
        "capacity": "к заказу услуг",
        "asset": "высоким качеством исполнения и сервисом"
    },
    "OTHER": {
        "profile": "компании",
        "clients": "клиентов",
        "capacity": "к вашим предложениям",
        "asset": "надежной репутацией и опытом"
    }
}


def generate_icebreaker_text(data: dict) -> str:
    # 1. Корректное имя адресата
    raw_lpr = str(data.get("lpr_name", "")).strip()
    stop_words = ["добрый день", "здравствуйте", "коллеги", "администратор", "none", ""]
    
    if not raw_lpr or raw_lpr.lower() in stop_words:
        greeting = "Здравствуйте!"
    else:
        first_name = raw_lpr.split()[0]
        greeting = f"Здравствуйте, {first_name}!"

    # 2. Отраслевые переменные
    niche_key = str(data.get("niche_key", "OTHER")).upper()
    lexicon = NICHE_LEXICON.get(niche_key, NICHE_LEXICON["OTHER"])

    title = str(data.get("title", "вашей компании")).strip()
    rating = data.get("rating", 4.7)
    comp_1 = data.get("comp_1") or data.get("competitor_1") or "соседним организациям"
    comp_2 = data.get("comp_2") or data.get("competitor_2") or "прямым конкурентам"
    
    lost_leads = data.get("lost_leads", "20–30")
    lost_revenue = data.get("lost_revenue", 0)
    
    if isinstance(lost_revenue, (int, float)):
        revenue_str = f"{lost_revenue:,}".replace(',', ' ') + " ₽"
    else:
        revenue_str = f"{lost_revenue} ₽"

    sender_name = str(data.get("sender_name", "Павел")).strip() or "Павел"

    # 3. Единое конверсионное тело письма
    message = f"""{greeting}

Меня зовут {sender_name}, команда аналитики PIN100.

Мы провели экспресс-аудит видимости карточки «{title}» на Яндекс Картах по 79 коммерческим факторам.

Ключевой вывод: профиль обладает высоким рейтингом ({rating}) и {lexicon['asset']}. Однако из-за технических пробелов в алгоритмической разметке карточка не удерживает верхние позиции в локальной выдаче. На практике это работает как фильтр, перенаправляющий целевой поток {lexicon['clients']} к вашим прямым соседям («{comp_1}» и «{comp_2}») вместо доступа {lexicon['capacity']}.

Масштаб потерь: по нашим расчетам, алгоритмический сбой приводит к потере порядка {lost_leads} горячих обращений ежемесячно. В пересчете на средний чек ниши это формирует кассовый разрыв около {revenue_str} упущенной выручки в месяц.

Мы собрали детальный 4-страничный PDF-отчет с точками слива трафика и планом их устранения.

Файл готов, рекламы внутри нет. Отправьте «Да» в ответном сообщении — пришлю аудит для ознакомления."""

    return message.strip()
