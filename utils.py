import re

# Отраслевой словарь: термины, обращение к ЛПР и специфика ниши
NICHE_VOCAB = {
    "DENTISTRY": {
        "niche_name": "стоматологий",
        "service_sample": "имплантации или лечению кариеса",
        "audience": "пациентов",
        "unit": "пациента",
        "lpr_default": "руководству клиники",
    },
    "BEAUTY_MEDICAL": {
        "niche_name": "клиник и косметологий",
        "service_sample": "процедурам и врачам",
        "audience": "клиентов",
        "unit": "клиента",
        "lpr_default": "управляющему",
    },
    "AUTO": {
        "niche_name": "автосервисов",
        "service_sample": "ремонту и диагностике",
        "audience": "автовладельцев",
        "unit": "машины",
        "lpr_default": "собственнику",
    },
    "HORECA": {
        "niche_name": "ресторанов",
        "service_sample": "бронированию и меню",
        "audience": "гостей",
        "unit": "столика",
        "lpr_default": "управляющему",
    },
    "OTHER": {
        "niche_name": "организаций",
        "service_sample": "услугам компании",
        "audience": "клиентов",
        "unit": "заказа",
        "lpr_default": "руководству",
    }
}

# Перевод технических кодов в живые бизнес-последствия (а не термины из БД)
KILLER_FLAW_DESCRIPTIONS = {
    "CONV-48.1": "нет быстрой кнопки онлайн-записи (пациенты в вечерние часы и с острой болью не могут записаться в один клик и сразу уходят к соседям)",
    "REP-32.2": "в ответах на претензии администраторы спорят с пациентами (для тех, кто впервые выбирает врача, оборонительный тон клиники — жесткий стоп-фактор)",
    "PROF-10.3": "в профиле нет четкого перечня услуг и врачей (Яндекс просто не показывает карточку по узким целевым запросам района)",
    "CONV-49.1": "нет внятного УТП и фактов (карточка выглядит обезличенно на фоне активных конкурентов)",
    "PROF-11.3": "в прейскуранте спрятаны стартовые цены (люди боятся скрытых наценок и выбирают открытые прайсы)",
    "REP-29.1": "свежие отзывы не обновлялись больше месяца (алгоритмы считают карточку затухающей и опускают в районной выдаче)",
    "CONV-50.1": "отключен чат на Картах, отсекая тех, кто не хочет звонить голосом",
    "CONT-38.1": "нет качественных фото кабинетов и оборудования (люди не видят условий и сомневаются в уровне клиники)"
}

def round_to_human_currency(val):
    """Округляет число до разговорных 'тыс. ₽' без роботизированной точности до рубля"""
    if not val:
        return "100 тыс."
    try:
        num = float(str(val).replace(" ", "").replace(",", "."))
        if num >= 1_000_000:
            return f"{round(num / 1_000_000, 1)} млн".replace(".0", "")
        if num >= 100_000:
            # Округляем до десятков тысяч (128 975 -> ~130 тыс.)
            rounded = int(round(num / 10_000.0) * 10)
            return f"~{rounded} тыс."
        if num >= 10_000:
            # Округляем до пяти тысяч
            rounded = int(round(num / 5_000.0) * 5)
            return f"~{rounded} тыс."
        return f"{int(num):,}".replace(",", " ")
    except Exception:
        return str(val)

def resolve_competitors(comp_1, comp_2):
    c1 = str(comp_1 or "").strip()
    c2 = str(comp_2 or "").strip()
    if c1 and c2:
        return f"«{c1}» или «{c2}»"
    if c1:
        return f"«{c1}»"
    if c2:
        return f"«{c2}»"
    return "прямым соседям по району"

def generate_icebreaker_text(data: dict, templates_dict: dict = None) -> str:
    """
    Генерирует лаконичное, персонализированное сообщение для мессенджеров (Telegram/WhatsApp).
    Никакого корпоративного канцелярита — фокус на конкретной проблеме и потерянных пациентах.
    """
    niche_key = str(data.get("niche_key") or "DENTISTRY").upper()
    vocab = NICHE_VOCAB.get(niche_key, NICHE_VOCAB["OTHER"])

    title = data.get("title") or "клиники"
    lpr_name = str(data.get("lpr_name") or "").strip()
    rating = str(round(float(data.get("rating") or 4.5), 1))
    score = float(data.get("score") or 0.0)
    is_leader = bool(data.get("is_leader") or score >= 75.0)

    comp_str = resolve_competitors(data.get("comp_1"), data.get("comp_2"))
    lost_leads = str(data.get("lost_leads") or "3–5")
    lost_revenue_str = round_to_human_currency(data.get("lost_revenue", 0))

    # Персональное приветствие
    if lpr_name:
        greeting = f"{lpr_name}, добрый день!"
    else:
        greeting = f"Добрый день! Подскажите, с кем можно пообщаться по развитию «{title}»?"

    # СЦЕНАРИЙ 1: ЛИДЕРЫ ЛОКАЦИИ (Балл >= 75.0)
    if is_leader:
        return (
            f"{greeting}\n\n"
            f"Обратил внимание на профиль «{title}» на Яндекс Картах. "
            f"У вас отличный рейтинг ({rating}) и сильное позиционирование, но из-за пары мелких "
            f"технических настроек часть поискового трафика в локации перетекает в {comp_str}.\n\n"
            f"По примерной оценке спроса района это минус {lost_leads} первичных {vocab['audience']} в месяц "
            f"({lost_revenue_str} ₽ кассы первого приема).\n\n"
            f"Собрали для вас наглядный 4-страничный аудит с разбором этих точек роста. "
            f"Имеет смысл скинуть файл сюда?"
        )

    # СЦЕНАРИЙ 2: ТРЕБУЕТ ОПТИМИЗАЦИИ (Балл < 75.0)
    # Находим главную причину потери конверсии
    fail_codes = data.get("top_fail_codes") or []
    killer_flaw = None
    for code in fail_codes:
        if code in KILLER_FLAW_DESCRIPTIONS:
            killer_flaw = KILLER_FLAW_DESCRIPTIONS[code]
            break
            
    if not killer_flaw:
        killer_flaw = "в карточке не настроена быстрая запись и не раскрыт спектр услуг"

    return (
        f"{greeting}\n\n"
        f"Заглянул в карточку «{title}» на Яндекс Картах. "
        f"Репутация крепкая ({rating}), но прямо сейчас клиника упускает первичных пациентов района. "
        f"Основная причина — {killer_flaw}.\n\n"
        f"В итоге пациенты, готовые прийти на прием на этой неделе, уходят в {comp_str}. "
        f"По емкости района это отток около {lost_leads} {vocab['audience']} в месяц (кассовый разрыв {lost_revenue_str} ₽).\n\n"
        f"Свели разбор ошибок и расчет потерь в короткий PDF на 4 страницы. "
        f"Прислать файл для ознакомления?"
    )
    
