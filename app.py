import streamlit as st
import requests
import time
import json
import numpy as np
import pandas as pd
import re
import itertools
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

# Импорты для зрения
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Настройка ИИ 
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-3.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден. AI-функции будут отключены.")
    ai_model = None

def send_telegram_alert(message):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        try:
            requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=5)
        except Exception:
            pass

# ==========================================
# 2. ПАРСЕР GOOGLE ТАБЛИЦЫ И APIFY
# ==========================================
@st.cache_resource
def init_google_sheets():
    try:
        creds_dict = json.loads(st.secrets["GCP_CREDENTIALS"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        return gspread.authorize(credentials).open_by_url(st.secrets["SPREADSHEET_URL"])
    except Exception as e:
        st.error(f"❌ Ошибка подключения к Google Sheets: {e}")
        st.stop()

def get_rules_from_sheets():
    doc = init_google_sheets()
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    for r in records:
        raw_val = r.get('Балл', 0.0)
        try:
            if isinstance(raw_val, (int, float)): 
                r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError:
            r['Балл'] = 0.0
        r['Статус'] = str(r.get('Статус', 'Заглушка')).strip()
    return records

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    if 'error' in run_req: raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception("⏱ Таймаут парсера.")
        time.sleep(5)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": raise Exception("Парсер завершился с ошибкой.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset or len(dataset) == 0: raise Exception("Парсер не смог получить данные (пустой ответ).")
    return dataset[0]

# ==========================================
# 3. МОДУЛЬНАЯ АРХИТЕКТУРА И АЛГОРИТМЫ
# ==========================================

def get_safe_list(data, keys):
    result = []
    for k in keys:
        val = data.get(k)
        if isinstance(val, list): result.extend(val)
        elif isinstance(val, dict): result.append(val)
    return result

def calculate_prof_rules(data):
    scores, logs = {}, []
    if data.get('isVerifiedOwner', False):
        for k in ['PROF-12.1', 'PROF-01.1', 'PROF-03.1', 'PROF-05.1', 'PROF-07.1']:
            scores[k] = True
        logs.append("✅ [PROF-12.1] Синяя галочка подтверждена.")
    else:
        if len(data.get('title', '')) > 2: scores['PROF-01.1'] = True
        if len(data.get('categories') or []) > 0: scores['PROF-03.1'] = True
        if data.get('phones'): scores['PROF-05.1'] = True
        if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = True

    phones = data.get('phones')
    if isinstance(phones, list):
        for p in phones:
            if "доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10:
                scores['PROF-05.2'] = True
                break
                
    features = data.get('features') or []
    if features: scores['PROF-08.1'] = True
    if len(features) >= 5: scores['PROF-08.2'] = True
    
    desc = data.get('description') or ''
    if len(desc) > 1500: scores['PROF-10.1'] = True
    
    website = data.get('url') or data.get('website') or ''
    if website: 
        scores['PROF-04.1'] = True
        if "utm_" in str(website).lower(): scores['PROF-04.2'] = True
            
    if data.get('requisites') or data.get('legalInfo'): scores['PROF-15.1'] = True

    schedule_str = str(data.get('workingHours') or data.get('schedule') or '').lower()
    if any(k in schedule_str for k in ['перерыв', 'special', 'intervals']): scores['PROF-07.2'] = True

    desc_and_features = f"{desc} {data.get('features', '')}".lower()
    if re.search(r'(основан[а-я]? в 19\d{2}|основан[а-я]? в 20\d{2}|работает с 19\d{2}|работает с 20\d{2}|since 19\d{2}|since 20\d{2})', desc_and_features):
        scores['PROF-14.1'] = True

    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    if len(products) >= 10:
        scores['PROF-11.1'] = True
        with_photo = sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image'))
        if with_photo / len(products) >= 0.8: scores['PROF-11.2'] = True
        with_price = sum(1 for p in products if p.get('price'))
        if with_price / len(products) >= 0.8: scores['PROF-11.3'] = True
        with_desc = sum(1 for p in products if len(str(p.get('description') or '')) > 50)
        if with_desc / len(products) >= 0.8: scores['PROF-11.4'] = True
        cat_set = set(p.get('category', {}).get('name') if isinstance(p.get('category'), dict) else p.get('category') for p in products)
        if len(cat_set) >= 2: scores['PROF-11.5'] = True
            
    links_str = f"{data.get('links', '')} {data.get('socials', '')}".lower()
    if any(s in links_str for s in ["t.me", "tg://", "wa.me", "whatsapp"]): scores['PROF-13.1'] = True
    if any(s in links_str for s in ["vk.com", "youtube", "dzen"]): scores['PROF-13.2'] = True

    return scores, logs

def calculate_cont_rules(data):
    scores, logs = {}, []
    photo_count = data.get('photoCount') or data.get('photosCount') or 0
    if photo_count >= 15: scores['CONT-36.1'] = True
    if photo_count >= 30: scores['CONT-36.2'] = True
    
    if data.get('stories') or data.get('storyUrls'): scores['CONT-44.1'] = True
    if data.get('panoramaUrl') or data.get('panoramas') or data.get('videos'): scores['CONT-42.1'] = True
        
    photos = get_safe_list(data, ['photos', 'images'])
    for p in photos:
        if any(kw in str(p).lower() for kw in ['внутри', 'интерьер', 'interior', 'inside', 'залы']):
            scores['CONT-43.1'] = True
            break
            
    return scores, logs

def calculate_rep_rules(data):
    scores, logs = {}, []
    rating = data.get('rating') or 0.0
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    if (data.get('reviewsCount') or data.get('ratingsCount') or 0) >= 50: scores['REP-28.1'] = True
    
    reviews = data.get('reviews')
    if isinstance(reviews, list) and len(reviews) > 0:
        dates = []
        for r in reviews[:20]:
            try:
                d_str = r.get('date') or r.get('createdAt')
                if d_str: dates.append(datetime.fromisoformat(d_str.replace('Z', '+00:00')))
            except: pass
            
        if dates:
            if (datetime.now(timezone.utc) - dates[0]).days < 14: scores['REP-29.1'] = True
                
        if len(dates) >= 3:
            diffs = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
            if diffs and (sum(d == 0 for d in diffs) / len(diffs)) < 0.3:
                scores['REP-29.2'] = True
                
        last_20 = reviews[:20]
        replied, total_days, valid_times, unans_neg, ans_pos = 0, 0, 0, 0, 0
        owner_texts = []
        
        with_photo = sum(1 for r in last_20 if r.get('photos') or r.get('images'))
        if len(last_20) > 0 and (with_photo / len(last_20)) >= 0.1: scores['REP-35.1'] = True
        
        for rev in last_20:
            r_rate = rev.get('rating') or 0
            reply = rev.get('reply') or rev.get('ownerAnswer')
            if reply:
                replied += 1
                if isinstance(reply, dict) and reply.get('text'): 
                    owner_texts.append(reply.get('text').lower())
                try:
                    r_d = datetime.fromisoformat((rev.get('date') or rev.get('createdAt')).replace('Z', '+00:00'))
                    a_d = datetime.fromisoformat((reply.get('date') or reply.get('createdAt') or reply.get('updatedAt')).replace('Z', '+00:00'))
                    if (a_d - r_d).days >= 0:
                        total_days += (a_d - r_d).days
                        valid_times += 1
                except: pass
            if r_rate <= 3 and not reply: unans_neg += 1
            if r_rate >= 4 and reply: ans_pos += 1
        
        if len(last_20) > 0 and (replied / len(last_20)) >= 0.9: scores['REP-30.1'] = True
        if valid_times > 0 and (total_days / valid_times) <= 3: scores['REP-30.2'] = True
        if unans_neg == 0 and len(last_20) > 0: scores['REP-32.1'] = True
        if ans_pos > 0: scores['REP-30.3'] = True
            
        if len(owner_texts) >= 2:
            is_templated = False
            for t1, t2 in itertools.combinations(owner_texts[:10], 2):
                words1, words2 = set(re.findall(r'\w+', t1)), set(re.findall(r'\w+', t2))
                if (len(words1 & words2) / max(1, len(words1 | words2))) > 0.8:
                    is_templated = True
                    break
            if not is_templated: scores['REP-31.1'] = True
        elif len(owner_texts) == 1: scores['REP-31.1'] = True

        if owner_texts:
            toxic_words = ['вранье', 'ложь', 'клевета', 'провокация', 'суд', 'неадекват', 'чушь', 'бред']
            if not any(w in t for t in owner_texts for w in toxic_words): scores['REP-32.2'] = True
            
            spam_fight_words = ['не были', 'не находим', 'в базе', 'уточните дату', 'номер телефона', 'вас нет', 'имя клиента']
            if any(w in t for t in owner_texts for w in spam_fight_words): scores['REP-33.1'] = True

    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    str_search = f"{data.get('links', '')} {data.get('features', '')} {data.get('socials', '')}".lower()
    
    # ПАТЧ: Добавлены системы бронирования ресторанов и клиник
    booking_systems = ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн', 'nethouse', 'leclick', 'tomesto', 'restoclub', 'afisha', 'prodoctorov', 'docdoc', 'sberhealth']
    
    if any(b in str_search for b in booking_systems):
        scores['CONV-48.1'] = True
        
    if "chat" in str_search or data.get('isChatEnabled'): scores['CONV-50.1'] = True
        
    if data.get('isChatEnabled') and (data.get('isAdvertiser') or "бот" in str_search):
        scores['CONV-50.2'] = True

    if data.get('posts') or data.get('news') or data.get('promos'): scores['CONV-51.1'] = True
    
    action_url = str(data.get('actionUrl') or data.get('bookingUrl') or '').lower()
    if action_url: 
        scores['CONV-47.1'] = True
        if any(b in action_url for b in booking_systems + ['whatsapp', 't.me', 'vk.com/app']):
            scores['CONV-47.2'] = True

    cover = str(data.get('coverPhotoUrl') or data.get('coverUrl') or '').lower()
    if cover and 'panorama' not in cover and 'streetview' not in cover:
        scores['CONV-46.1'] = True

    if data.get('questionsAndAnswers') or data.get('faq') or data.get('qna'): scores['CONV-52.1'] = True
        
    promos = get_safe_list(data, ['promos'])
    posts = get_safe_list(data, ['posts', 'news'])
    if promos:
        scores['CONV-51.2'] = True
    else:
        recent_promo = False
        for p in posts:
            if any(w in str(p.get('text', '')).lower() for w in ['акция', 'скидка', 'спецпредложение', 'до конца']):
                recent_promo = True
                break
        if recent_promo: scores['CONV-51.2'] = True

    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    for p in products:
        if p.get('oldPrice') or p.get('discount') or any(kw in str(p).lower() for kw in ['хит', 'новинка', 'скидка', 'акция']):
            scores['CONV-53.1'] = True
            break
            
    return scores, logs

def calculate_seo_rules(data):
    scores, logs = {}, []
    if len(data.get('address') or '') > 5: scores['SEO-18.1'] = True
    str_features = str(data.get('features') or '').lower()
    if data.get('serviceArea') or data.get('deliveryArea') or any(k in str_features for k in ['выезд', 'доставк', 'зона обслуживани', 'радиус']):
        scores['SEO-18.2'] = True
        
    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    if products:
        avg_words = sum(len(str(p.get('name', '')).split()) for p in products) / len(products)
        if avg_words >= 2.0:
            scores['SEO-21.1'] = True
            
    return scores, logs

def calculate_act_rules(data):
    scores, logs = {}, []
    fresh, now = False, datetime.now(timezone.utc)
    posts_with_images = False
    
    posts = get_safe_list(data, ['posts', 'news', 'promos'])
    for p in posts:
        try:
            p_date = datetime.fromisoformat((p.get('date') or p.get('publishedAt') or p.get('createdAt')).replace('Z', '+00:00'))
            if (now - p_date).days <= 30: 
                fresh = True
                if p.get('imageUrl') or p.get('images') or p.get('photoUrl'): posts_with_images = True
        except: pass
        
    if not fresh and (data.get('stories') or data.get('storyUrls')): fresh = True
    if fresh: scores['ACT-68.1'] = True
    if posts_with_images or data.get('stories') or data.get('storyUrls'): scores['ACT-67.1'] = True
    if data.get('isAdvertiser') or data.get('advertiser'): scores['ACT-69.1'] = True
        
    return scores, logs

# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ: ТЕКСТЫ (Адаптировано под HoReCa) ===
def calculate_ai_rules(data):
    scores, logs = {}, []
    if ai_model is None: return scores, logs, "Модель ИИ отключена."
        
    title = data.get('title', '')
    description = data.get('description', '')
    category = data.get('categories', [{}])[0].get('name', '') if data.get('categories') else ''
    cats_str = ", ".join([c.get('name', str(c)) for c in data.get('categories', [])])
    
    owner_texts, client_texts = [], []
    for rev in data.get('reviews', [])[:15]:
        if rev.get('text'): client_texts.append(rev.get('text'))
        reply = rev.get('reply') or rev.get('ownerAnswer')
        if isinstance(reply, dict) and reply.get('text'): owner_texts.append(reply.get('text'))
                
    owner_str = " | ".join(owner_texts[:3]) if owner_texts else "Ответов нет"
    client_str = " | ".join(client_texts[:5]) if client_texts else "Отзывов нет"
    faq_str = " | ".join([f"В: {q.get('question')} О: {q.get('answer')}" for q in get_safe_list(data, ['questionsAndAnswers', 'faq', 'qna'])[:3]]) if get_safe_list(data, ['questionsAndAnswers', 'faq', 'qna']) else "FAQ нет"
    
    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    prod_str = " | ".join([str(p.get('description')) for p in prods[:5] if p.get('description')]) if prods else "Описаний нет"
        
    prompt = f"""
    Ты Senior SEO-специалист и маркетолог.
    Шаг 1: Определи нишу (Название: {title}, Категория: {category}). 
    ВАЖНО: Если это Ресторан/Бар/HoReCa или премиум-сегмент — будь лояльнее. В ресторанах не должно быть жесткого SEO и агрессивных призывов к действию, текст должен быть вкусным и атмосферным.
    Шаг 2: Ответь строго "true" или "false" в формате JSON. Никакого Markdown.

    ОПИСАНИЕ: "{description}"
    ОТВЕТЫ: "{owner_str}"
    ОТЗЫВЫ: "{client_str}"
    ТОВАРЫ: "{prod_str}"
    FAQ: "{faq_str}"

    ВОПРОСЫ (ключи JSON):
    "PROF-10.6": Есть ли в описании призыв к действию (или мягкое приглашение для ресторанов)?
    "PROF-10.3": Перечислены ли конкретные услуги/особенности меню?
    "CONV-49.1": Есть ли в начале описания сильное УТП/Концепция?
    "SEO-18.3": Есть ли в описании названия городов/районов (топонимы)?
    "PROF-10.4": Есть ли в описании факты, цифры или четкая концепция без воды?
    "CONV-49.2": Есть ли в описании измеримые показатели (годы, метрики)?
    "PROF-01.2": Является ли название чистым брендом без SEO-спама?
    "REP-31.2": Есть ли в ответах владельца корпоративный стиль (если ответов нет - false)?
    "CONV-52.2": Снимает ли FAQ вопросы клиентов?
    "PROF-02.1": Соответствует ли Категория Описанию?
    "PROF-03.2": Нет ли "мусорных" категорий?
    "SEO-17.1": Есть ли в Описании ключи ниши (для ресторанов - атмосферные LSI)?
    "SEO-17.2": Описание читаемое, без SEO-переспама?
    "SEO-17.3": Есть ли LSI-термины ниши?
    "CONV-49.4": Закрывает ли текст боли клиентов (вкус, атмосфера, сервис)?
    "SEO-19.1": Вплетает ли владелец в Ответы коммерческие ключи/названия блюд?
    "SEO-19.2": Упоминают ли клиенты в Отзывах конкретные услуги/блюда?
    "SEO-21.2": Содержат ли Описания товаров развернутые SEO-термины (вкусное описание)?
    """
    try:
        response = ai_model.generate_content(prompt)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res = json.loads(match.group(0))
            for k in res: 
                if res[k]: scores[k] = True
        else: return scores, logs, "Невалидный JSON от ИИ."
    except Exception as e: return scores, logs, str(e)
    return scores, logs, None


# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ: ЗРЕНИЕ (Агрессивный сканер) ===
def fetch_image_for_ai(url):
    try:
        if not url.startswith('http'): url = 'https:' + url if url.startswith('//') else 'https://' + url
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content)).convert('RGB')
            img.thumbnail((800, 800)) 
            return img
    except: pass
    return None

def calculate_vision_rules(data):
    scores, logs = {}, []
    if ai_model is None: return scores, logs, None
        
    image_urls = []
    
    # 1. Сначала ищем по стандартным ключам
    cover = str(data.get('coverPhotoUrl') or data.get('coverUrl') or '')
    if cover and 'panorama' not in cover: image_urls.append(cover)
    for p in get_safe_list(data, ['photos', 'images'])[:4]:
        u = p.get('url') if isinstance(p, dict) else str(p)
        if u and 'panorama' not in u: image_urls.append(u)
            
    # 2. ПАТЧ: Агрессивный поиск ВСЕХ ссылок на картинки в сыром JSON, если по стандарту ничего не нашлось
    if not image_urls:
        raw_string = json.dumps(data)
        found_urls = re.findall(r'https?://[^\s<>"]+?\.jpg|https?://avatars\.mds\.yandex\.net/[^\s<>"]+', raw_string)
        # Убираем дубликаты и панорамы
        valid_urls = list(set([u for u in found_urls if 'panorama' not in u and 'streetview' not in u]))
        image_urls = valid_urls[:5] # Берем до 5 штук
        if image_urls:
            logs.append(f"ℹ️ [AI-Vision] Стандартная галерея пуста, но найдено {len(image_urls)} скрытых фото через RegEx.")

    if not image_urls:
        logs.append("⚠️ [AI-Vision] Картинки полностью отсутствуют в данных карточки. Пропуск визуального блока.")
        return scores, logs, None

    with ThreadPoolExecutor(max_workers=5) as executor:
        pil_images = list(filter(None, executor.map(fetch_image_for_ai, image_urls)))
        
    if not pil_images:
        logs.append("⚠️ [AI-Vision] Не удалось скачать фото (ошибка 403/404). Пропуск.")
        return scores, logs, None
        
    prompt = """
    Ты Арт-директор. Изучи эти фотографии компании (первая - обложка).
    Ответь строго в JSON (true/false) на 7 вопросов. Никакого Markdown.

    ВОПРОСЫ (ключи JSON):
    "CONV-49.3": Есть ли на первой картинке (обложке) читаемый добавленный текст (оффер/скидка), который наложен поверх фото? (Если это просто вывеска на здании - false).
    "CONT-37.2": Выглядят ли фото как реальные живые кадры компании, а НЕ как пластиковые стоковые фото из интернета с идеальными моделями?
    "CONT-37.3": Фотографии хорошо освещены (не слишком темные, нормальная контрастность)?
    "CONT-39.1": Есть ли на фото лица людей, сотрудники, гости или живая команда в процессе работы/отдыха?
    "CONT-40.1": Есть ли на фото "бэкстейдж" (виден процесс работы, приготовление блюд, оказание услуги или производство)?
    "CONT-41.1": Есть ли предметные фотографии (товар, еда, результат работы сняты крупно)?
    "CONT-41.2": Высокая ли детализация на предметных фото (фокус на деталях, качественная макро-съемка)?
    """
    try:
        response = ai_model.generate_content([prompt] + pil_images)
        match = re.search(r'\{.*\}', response.text, re.DOTALL)
        if match:
            res = json.loads(match.group(0))
            for k in res: 
                if res[k]: scores[k] = True
            logs.append("✅ [AI-Vision] Фотографии успешно проанализированы нейросетью.")
        else: logs.append("⚠️ [AI-Vision] Невалидный JSON-ответ.")
    except Exception as e: logs.append(f"⚠️ [AI-Vision] Сбой Gemini Vision: {e}")
        
    return scores, logs, None

def calculate_all_python_rules(data):
    all_scores, all_logs = {}, []
    global_ai_error = None
    
    mods = [
        calculate_prof_rules(data), calculate_cont_rules(data), calculate_rep_rules(data),
        calculate_conv_rules(data), calculate_seo_rules(data), calculate_act_rules(data)
    ]
    for s_dict, l_list in mods:
        all_scores.update(s_dict)
        all_logs.extend(l_list)
        
    ai_scores, ai_logs, ai_err = calculate_ai_rules(data)
    all_scores.update(ai_scores)
    all_logs.extend(ai_logs)
    if ai_err: global_ai_error = ai_err
        
    vis_scores, vis_logs, vis_err = calculate_vision_rules(data)
    all_scores.update(vis_scores)
    all_logs.extend(vis_logs)
        
    return all_scores, all_logs, global_ai_error

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА
# ==========================================
st.set_page_config(page_title="MAP100 | Нейро-Аудитор", page_icon="🧠", layout="wide")

try:
    rules_data = get_rules_from_sheets()
except Exception as e:
    st.error("⚠️ Не удалось загрузить базу правил. Проверьте Google Sheets API.")
    st.stop()

with st.sidebar:
    st.header("🎛 Ручная оценка")
    st.write("Все метрики автоматизированы. Ручной ввод отключен за ненадобностью.")

st.title("📍 MAP100: AI-Аудитор (Версия 11.1 - Адаптация и Зрение 2.0)")

stat_python = sum(1 for r in rules_data if r.get('Статус') == "Python")
stat_manual = sum(1 for r in rules_data if r.get('Статус') == "Ручной")
stat_stub = sum(1 for r in rules_data if r.get('Статус') not in ["Python", "Ручной"] and str(r.get('Код', '')).strip())

col_s1, col_s2, col_s3 = st.columns(3)
col_s1.metric("🟢 Готово (Python+AI)", stat_python)
col_s2.metric("🧠 Ручной режим", stat_manual)
col_s3.metric("🟡 В разработке (Заглушки)", stat_stub)
st.divider()

yandex_url = st.text_input("Ссылка на карточку Яндекс.Бизнеса")

if st.button("🚀 Запустить аудит", type="primary", use_container_width=True):
    if not yandex_url or "yandex" not in yandex_url.lower():
        st.error("❌ Введите корректную ссылку на Яндекс.Карты.")
    else:
        doc = init_google_sheets()
        with st.spinner("Синтезирую данные: парсер + ИИ читает тексты + ИИ смотрит фото..."):
            try:
                raw_yandex_data = fetch_apify_data(yandex_url)
                company_name = raw_yandex_data.get('title', 'Без названия')
                python_scores_dict, python_logs, ai_error = calculate_all_python_rules(raw_yandex_data)
                
                if ai_error:
                    st.error(f"🚨 КРИТИЧЕСКАЯ ОШИБКА ИИ: {ai_error}")
                    send_telegram_alert(f"🚨 Ошибка ИИ в MAP100!\nКомпания: {company_name}\nСсылка: {yandex_url}\nПричина: {ai_error}")
                    
            except Exception as e:
                st.error(f"⚠️ Ошибка работы алгоритма: {e}")
                st.stop()
                
            final_scores_dict = {}
            detailed_results = []
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                max_score = float(r.get('Балл', 0.0))
                
                current_val = max_score if python_scores_dict.get(code) else 0.0
                final_scores_dict[code] = current_val
                
                comment = ""
                specific_log = None
                for log in python_logs:
                    if f"[{code}]" in log:
                        parts = log.split("]", 1)
                        if len(parts) > 1:
                            specific_log = parts[1].strip()
                            break
                if current_val > 0:
                    comment = f"✅ {specific_log}" if specific_log else "✅ Выполнено"
                else:
                    comment = "❌ Не выполнено / Данные отсутствуют"
                    
                detailed_results.append({
                    "Код": code, "Критерий": name, "Балл": current_val, 
                    "Макс": max_score, "Комментарий": comment
                })
                
            final_total_score = sum(final_scores_dict.values())
            
            st.divider()
            col1, col2 = st.columns([3, 1])
            with col1: st.subheader(f"🏢 {company_name}")
            with col2: 
                color = "normal" if final_total_score >= 80 else ("off" if final_total_score >= 50 else "inverse")
                st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100", delta_color=color)

            with st.expander("📊 Детализация баллов по критериям", expanded=True):
                st.dataframe(
                    pd.DataFrame(detailed_results), 
                    column_config={
                        "Код": st.column_config.TextColumn("Код", width="small"), 
                        "Критерий": st.column_config.TextColumn("Критерий", width="medium"), 
                        "Балл": st.column_config.NumberColumn("Балл", format="%.1f"), 
                        "Макс": st.column_config.NumberColumn("Макс.", format="%.1f"), 
                        "Комментарий": st.column_config.TextColumn("Комментарий (Почему так)", width="large")
                    }, 
                    hide_index=True, use_container_width=True
                )

            with st.expander("🛠️ Системные логи (Отладка)", expanded=False):
                for log in python_logs: st.write(log)

            try:
                results_sheet = doc.worksheet("Results")
                headers = results_sheet.row_values(1)
                if not headers: headers = ["Дата", "Ссылка", "Компания", "Общий балл"]
                    
                headers_changed = False
                for c in final_scores_dict.keys():
                    if c not in headers:
                        headers.append(c)
                        headers_changed = True
                        
                if headers_changed:
                    cell_list = results_sheet.range(1, 1, 1, len(headers))
                    for i, val in enumerate(headers): cell_list[i].value = val
                    results_sheet.update_cells(cell_list)
                    
                row_data = []
                for h in headers:
                    if h == "Дата": row_data.append(time.strftime("%d.%m.%Y %H:%M:%S"))
                    elif h == "Ссылка": row_data.append(yandex_url)
                    elif h == "Компания": row_data.append(company_name)
                    elif h == "Общий балл": row_data.append(final_total_score)
                    else: row_data.append(final_scores_dict.get(h, 0.0))
                        
                results_sheet.append_row(row_data)
                st.success("✅ Результат успешно сохранен в базу!")
            except: pass
