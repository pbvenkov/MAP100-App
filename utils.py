import re

NICHE_LEXICON = {
    "DENTISTRY": {
        "clients": "пациенты",
        "niche_genitive": "стоматологии",
        "leads_type": "записей",
        "business_plural": "клиниками",
        "business_genitive": "клиники",
        "business_noun": "клиника",
        "examples": "имплантацию, протезирование или лечение кариеса",
        "target_roles": "главврача или управляющего"
    },
    "BEAUTY_MEDICAL": {
        "clients": "пациенты и гости",
        "niche_genitive": "медицинские центры и клиники",
        "leads_type": "записей на процедуры",
        "business_plural": "центрами",
        "business_genitive": "центра",
        "business_noun": "центр",
        "examples": "косметологию, чек-апы или диагностику",
        "target_roles": "главврача или управляющего"
    },
    "HORECA": {
        "clients": "гости",
        "niche_genitive": "рестораны и кафе",
        "leads_type": "бронирований и заказов",
        "business_plural": "заведениями",
        "business_genitive": "заведения",
        "business_noun": "заведение",
        "examples": "банкеты, завтраки или блюда кухни",
        "target_roles": "управляющего или владельца"
    },
    "AUTO": {
        "clients": "автовладельцы",
        "niche_genitive": "автосервисы и техцентры",
        "leads_type": "заездов на обслуживание",
        "business_plural": "техцентрами",
        "business_genitive": "сервиса",
        "business_noun": "техцентр",
        "examples": "диагностику, сход-развал или ремонт подвески",
        "target_roles": "руководителя сервиса или владельца"
    },
    "EDUCATION": {
        "clients": "родители и ученики",
        "niche_genitive": "учебные и языковые центры",
        "leads_type": "заявок на обучение",
        "business_plural": "школами и центрами",
        "business_genitive": "центра",
        "business_noun": "центр",
        "examples": "подготовку к экзаменам, курсы или пробные занятия",
        "target_roles": "директора или руководителя"
    },
    "RETAIL": {
        "clients": "покупатели",
        "niche_genitive": "специализированные магазины",
        "leads_type": "покупательского потока",
        "business_plural": "магазинами",
        "business_genitive": "магазина",
        "business_noun": "магазин",
        "examples": "конкретные бренды, каталоги или категории товаров",
        "target_roles": "директора или владельца"
    },
    "B2B": {
        "clients": "заказчики",
        "niche_genitive": "поставщиков и оптовые компании",
        "leads_type": "входящих коммерческих запросов",
        "business_plural": "поставщиками",
        "business_genitive": "компании",
        "business_noun": "компания",
        "examples": "оптовые поставки, расчет партии или каталоги продукции",
        "target_roles": "коммерческого директора или руководителя"
    },
    "B2B_HEAVY": {
        "clients": "корпоративные заказчики",
        "niche_genitive": "производства и промышленные предприятия",
        "leads_type": "тендерных и прямых заявок",
        "business_plural": "производителями",
        "business_genitive": "предприятия",
        "business_noun": "предприятие",
        "examples": "производственные мощности, номенклатуру или техусловия",
        "target_roles": "генерального директора или собственника"
    },
    "SERVICES": {
        "clients": "клиенты",
        "niche_genitive": "сервисные компании",
        "leads_type": "обращений за услугами",
        "business_plural": "компаниями",
        "business_genitive": "компании",
        "business_noun": "компания",
        "examples": "срочные вызовы, тарифы или конкретные услуги",
        "target_roles": "руководителя или владельца"
    },
    "OTHER": {
        "clients": "клиенты",
        "niche_genitive": "организации",
        "leads_type": "первичных обращений",
        "business_plural": "организациями",
        "business_genitive": "организации",
        "business_noun": "компания",
        "examples": "ключевой спектр услуг или условия",
        "target_roles": "руководителя или управляющего"
    }
}

DEFAULT_FALLBACK_TEMPLATE = """{greeting}

Меня зовут {sender_name}, я анализирую, как {clients} находят {niche_genitive} на Яндекс Картах. На этой неделе мы сравнивали, как распределяется поток {leads_type} между {business_plural} вашего района.

У «{title}» высокая репутация и сильная оценка ({rating}). Но если житель района ищет в поиске конкретную услугу (например, {examples}), профиль {business_genitive} не появляется в топе выдачи. В карточке не выведен прайс, и {clients} сразу уходят {comp_phrase}.

По трафику локации {business_noun} каждый месяц упускает около {lost_leads} первичных обращений (это порядка {revenue_str} недополученной выручки).

Мы свели эти технические ошибки в короткий 4-страничный разбор. Скинуть сюда PDF для {target_roles}? (можно просто ответить «Да» или ➕)"""


def _clean_name(raw_name: str) -> str:
    if not raw_name:
        return ""
    return str(raw_name).strip('«»"\' \t\n\r')


def _build_competitors_phrase(comp_1: str, comp_2: str) -> str:
    c1 = _clean_name(comp_1)
    c2 = _clean_name(comp_2)
    stop_comp = {"соседним организациям", "прямым конкурентам", "соседним клиникам", "конкурентам", ""}

    has_c1 = bool(c1 and c1.lower() not in stop_comp)
    has_c2 = bool(c2 and c2.lower() not in stop_comp)

    if has_c1 and has_c2:
        return f"в «{c1}» или «{c2}»"
    if has_c1:
        return f"в «{c1}» или к другим соседям"
    if has_c2:
        return f"в «{c2}» или к другим соседям"
    return "к вашим прямым соседям"


def generate_icebreaker_text(data: dict, templates_dict: dict = None) -> str:
    # 1. Формирование корректного обращения к ЛПР
    raw_lpr = str(data.get("lpr_name", "")).strip()
    stop_names = {"добрый день", "здравствуйте", "коллеги", "администратор", "none", "null", ""}
    first_token = re.sub(r'[^\w\-]', '', raw_lpr.split()[0]) if raw_lpr else ""
    
    if first_token and first_token.lower() not in stop_names:
        greeting = f"Добрый день, {first_token}!"
    else:
        greeting = "Добрый день!"

    # 2. Отраслевой словарь
    niche_key = str(data.get("niche_key", "OTHER")).upper()
    lex = NICHE_LEXICON.get(niche_key, NICHE_LEXICON["OTHER"])

    # 3. Чистка значений
    title = _clean_name(str(data.get("title", "вашей компании")))
    
    try:
        rating_val = float(str(data.get("rating", 4.7)).replace(',', '.'))
        rating = round(rating_val, 1)
        if rating <= 0.0:
            rating = 4.7
    except Exception:
        rating = 4.7

    comp_phrase = _build_competitors_phrase(
        data.get("comp_1") or data.get("competitor_1") or "",
        data.get("comp_2") or data.get("competitor_2") or ""
    )

    lost_leads = str(data.get("lost_leads", "30–40")).strip()
    raw_rev = data.get("lost_revenue", 0)
    if isinstance(raw_rev, (int, float)):
        revenue_str = f"{int(raw_rev):,}".replace(',', ' ') + " ₽"
    else:
        clean_rev = str(raw_rev).replace('₽', '').strip()
        revenue_str = f"{clean_rev} ₽"

    sender_name = _clean_name(str(data.get("sender_name", "Павел"))) or "Павел"

    context = {
        "greeting": greeting,
        "sender_name": sender_name,
        "title": title,
        "rating": rating,
        "comp_phrase": comp_phrase,
        "lost_leads": lost_leads,
        "revenue_str": revenue_str,
        "clients": lex["clients"],
        "niche_genitive": lex["niche_genitive"],
        "leads_type": lex["leads_type"],
        "business_plural": lex["business_plural"],
        "business_genitive": lex["business_genitive"],
        "business_noun": lex["business_noun"],
        "examples": lex["examples"],
        "target_roles": lex["target_roles"]
    }

    # 4. Выбор шаблона (Ниша -> DEFAULT -> Встроенный)
    tpl_source = DEFAULT_FALLBACK_TEMPLATE
    if templates_dict and isinstance(templates_dict, dict):
        tpl_source = templates_dict.get(niche_key) or templates_dict.get("DEFAULT") or DEFAULT_FALLBACK_TEMPLATE

    # 5. Безопасная подстановка без падений на лишних фигурных скобках
    class SafeDict(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    return tpl_source.format_map(SafeDict(context)).strip()
