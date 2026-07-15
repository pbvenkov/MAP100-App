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

# === НОВЫЕ ИМПОРТЫ ДЛЯ ЗРЕНИЯ ИИ ===
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

# Настройка ИИ (СТРОГО gemini-3.5-flash)
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
        logs.append("✅ [PROF-12.1] Синяя галочка (Верифицирован) подтверждена.")
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
    
    if len(features) >= 5:
        scores['PROF-08.2'] = True
        logs.append("✅ [PROF-08.2] Найдено более 5 нишевых атрибутов (особенностей).")
    
    desc = data.get('description') or ''
    if len(desc) > 1500: scores['PROF-10.1'] = True
    
    website = data.get('url') or data.get('website') or ''
    if website: 
        scores['PROF-04.1'] = True
        if "utm_" in str(website).lower(): scores['PROF-04.2'] = True
            
    if data.get('requisites') or data.get('legalInfo'): 
        scores['PROF-15.1'] = True
        logs.append("✅ [PROF-15.1] Заполнена вкладка с юридическими данными.")

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
        cat_set = set()
        for p in products:
            cat = p.get('category')
            if isinstance(cat, dict): cat_set.add(cat.get('name'))
            else: cat_set.add(cat)
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
    
    if data.get('stories') or data.get('storyUrls'): 
        scores['CONT-44.1'] = True
        logs.append("✅ [CONT-44.1] В карточке найдены Истории (Stories).")
        
    if data.get('panoramaUrl') or data.get('panoramas') or data.get('videos'): 
        scores['CONT-42.1'] = True
        logs.append("✅ [CONT-42.1] Найдено видео или 3D-панорама.")
        
    photos = get_safe_list(data, ['photos', 'images'])
    for p in photos:
        if any(kw in str(p).lower() for kw in ['внутри', 'интерьер', 'interior', 'inside', 'залы']):
            scores['CONT-43.1'] = True
            logs.append("✅ [CONT-43.1] В галерее найдены фотографии 'Интерьер/Внутри'.")
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
                logs.append("✅ [REP-29.2] Распределение отзывов равномерное (нет спам-накруток в один день).")
                
        last_20 = reviews[:20]
        replied, total_days, valid_times, unans_neg, ans_pos = 0, 0, 0, 0, 0
        owner_texts = []
        
        with_photo = sum(1 for r in last_20 if r.get('photos') or r.get('images'))
        if len(last_20) > 0 and (with_photo / len(last_20)) >= 0.1: 
            scores['REP-35.1'] = True
            logs.append(f"✅ [REP-35.1] Доля отзывов с фото > 10% ({with_photo} шт).")
        
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
        
        if len(last_20) > 0 and (replied / len(last_20)) >= 0.9: 
            scores['REP-30.1'] = True
            logs.append("✅ [REP-30.1] Владелец ответил на 90%+ отзывов.")
        if valid_times > 0 and (total_days / valid_times) <= 3: 
            scores['REP-30.2'] = True
            logs.append("✅ [REP-30.2] Средняя скорость ответа <= 3 дней.")
        if unans_neg == 0 and len(last_20) > 0: 
            scores['REP-32.1'] = True
            logs.append("✅ [REP-32.1] Нет брошенного негатива.")
        if ans_pos > 0: scores['REP-30.3'] = True
            
        if len(owner_texts) >= 2:
            is_templated = False
            for t1, t2 in itertools.combinations(owner_texts[:10], 2):
                words1, words2 = set(re.findall(r'\w+', t1)), set(re.findall(r'\w+', t2))
                if (len(words1 & words2) / max(1, len(words1 | words2))) > 0.8:
                    is_templated = True
                    break
            if not is_templated:
                scores['REP-31.1'] = True
                logs.append("✅ [REP-31.1] Тексты ответов уникальны (не скопированы).")
        elif len(owner_texts) == 1: scores['REP-31.1'] = True

        if owner_texts:
            toxic_words = ['вранье', 'ложь', 'клевета', 'провокация', 'суд', 'неадекват', 'чушь', 'бред']
            if not any(w in t for t in owner_texts for w in toxic_words):
                scores['REP-32.2'] = True
                logs.append("✅ [REP-32.2] В ответах отсутствует агрессия и токсичность.")
                
        if owner_texts:
            spam_fight_words = ['не были', 'не находим', 'в базе', 'уточните дату', 'номер телефона', 'вас нет', 'имя клиента']
            if any(w in t for t in owner_texts for w in spam_fight_words):
                scores['REP-33.1'] = True
                logs.append("✅ [REP-33.1] Владелец оспаривает спам (запрашивает детали визита в негативе).")

    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    str_search = f"{data.get('links', '')} {data.get('features', '')} {data.get('socials', '')}".lower()
    
    if any(b in str_search for b in ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн', 'nethouse']):
        scores['CONV-48.1'] = True
        logs.append("✅ [CONV-48.1] Найдена система онлайн-записи.")
        
    if "chat" in str_search or data.get('isChatEnabled'): 
        scores['CONV-50.1'] = True
        
    if data.get('isChatEnabled') and (data.get('isAdvertiser') or "бот" in str_search):
        scores['CONV-50.2'] = True
        logs.append("✅ [CONV-50.2] Настроены быстрые ответы / бот.")

    if data.get('posts') or data.get('news') or data.get('promos'): scores['CONV-51.1'] = True
    
    action_url = str(data.get('actionUrl') or data.get('bookingUrl') or '').lower()
    if action_url: 
        scores['CONV-47.1'] = True
        logs.append("✅ [CONV-47.1] Настроена главная кнопка действия.")
        if any(b in action_url for b in ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'whatsapp', 't.me', 'vk.com/app', 'nethouse']):
            scores['CONV-47.2'] = True
            logs.append("✅ [CONV-47.2] Актуальный виджет: кнопка ведет на рабочий инструмент записи/связи.")

    cover = str(data.get('coverPhotoUrl') or data.get('coverUrl') or '').lower()
    if cover and 'panorama' not in cover and 'streetview' not in cover:
        scores['CONV-46.1'] = True
        logs.append("✅ [CONV-46.1] Обложка установлена вручную (не авто-панорама).")

    if data.get('questionsAndAnswers') or data.get('faq') or data.get('qna'): 
        scores['CONV-52.1'] = True
        logs.append("✅ [CONV-52.1] Заполнен блок FAQ.")
        
    promos = get_safe_list(data, ['promos'])
    posts = get_safe_list(data, ['posts', 'news'])
    if promos:
        scores['CONV-51.2'] = True
        logs.append("✅ [CONV-51.2] Найдена активная промоакция в специальном блоке.")
    else:
        recent_promo_post = False
        for p in posts:
            p_text = str(p.get('text', '')).lower()
            if any(w in p_text for w in ['акция', 'скидка', 'спецпредложение', 'до конца']):
                recent_promo_post = True
                break
        if recent_promo_post:
            scores['CONV-51.2'] = True
            logs.append("✅ [CONV-51.2] Найдена активная промоакция (в новостях/постах).")

    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    for p in products:
        if p.get('oldPrice') or p.get('discount') or any(kw in str(p).lower() for kw in ['хит', 'новинка', 'скидка', 'акция']):
            scores['CONV-53.1'] = True
            logs.append("✅ [CONV-53.1] В товарах найден бейдж (Хит, Скидка).")
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
            logs.append("✅ [SEO-21.1] Названия товаров содержат расширенные запросы (длина названия > 1 слова).")
            
    return scores, logs

def calculate_act_rules(data):
    scores, logs = {}, []
    fresh, now = False, datetime.now(timezone.utc)
    posts_with_images = False
    
    posts = get_safe_list(data, ['posts', 'news', 'promos'])
    for p in posts:
        try:
            p_date_str = p.get('date') or p.get('publishedAt') or p.get('createdAt')
            p_date = datetime.fromisoformat(p_date_str.replace('Z', '+00:00'))
            if (now - p_date).days <= 30: 
                fresh = True
                if p.get('imageUrl') or p.get('images') or p.get('photoUrl'):
                    posts_with_images = True
        except: pass
        
    if not fresh and (data.get('stories') or data.get('storyUrls')): fresh = True
        
    if fresh: 
        scores['ACT-68.1'] = True
        logs.append("✅ [ACT-68.1] Найдена свежая активность (<30 дней).")
        
    if posts_with_images or data.get('stories') or data.get('storyUrls'):
        scores['ACT-67.1'] = True
        logs.append("✅ [ACT-67.1] Регулярность фото: найден свежий визуальный контент (<30 дней).")
        
    if data.get('isAdvertiser') or data.get('advertiser'): 
        scores['ACT-69.1'] = True
        logs.append("✅ [ACT-69.1] Карточка оплатила Приоритетное размещение.")
        
    return scores, logs

# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ: ТЕКСТЫ ===
def calculate_ai_rules(data):
    scores, logs = {}, []
    ai_critical_error = None
    
    if ai_model is None: 
        return scores, logs, "Модель ИИ не инициализирована (проверьте API-ключ Gemini)."
        
    title = data.get('title', '')
    description = data.get('description', '')
    category = ""
    if data.get('categories') and len(data['categories']) > 0:
        cat_obj = data['categories'][0]
        category = cat_obj.get('name') if isinstance(cat_obj, dict) else str(cat_obj)
        
    all_categories = []
    if data.get('categories'):
        for c in data['categories']:
            all_categories.append(c.get('name') if isinstance(c, dict) else str(c))
    cats_str = ", ".join(all_categories)
    
    reviews_data = data.get('reviews')
    owner_texts = []
    client_texts = []
    if isinstance(reviews_data, list):
        for rev in reviews_data[:15]:
            if rev.get('text'): client_texts.append(rev.get('text'))
            reply = rev.get('reply') or rev.get('ownerAnswer')
            if isinstance(reply, dict) and reply.get('text'): 
                owner_texts.append(reply.get('text'))
                
    owner_replies_str = " | ".join(owner_texts[:3]) if owner_texts else "Ответов нет"
    client_reviews_str = " | ".join(client_texts[:5]) if client_texts else "Отзывов нет"
    
    faq_list = get_safe_list(data, ['questionsAndAnswers', 'faq', 'qna'])
    faq_str_list = [f"В: {q.get('question')} О: {q.get('answer')}" for q in faq_list[:3]]
    faq_str = " | ".join(faq_str_list) if faq_str_list else "FAQ нет"
    
    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    prod_desc_list = [str(p.get('description')) for p in products[:5] if p.get('description')]
    prod_desc_str = " | ".join(prod_desc_list) if prod_desc_list else "Описаний товаров нет"
        
    prompt = f"""
    Ты Senior SEO-специалист и маркетолог. Проанализируй данные компании и ответь на 18 вопросов.
    Шаг 1: Определи нишу бизнеса по Названию и Категории. Вспомни главные "боли" клиентов этой ниши и ее LSI-словарь (ключевые термины).
    Шаг 2: Ответь на вопросы строго "true" или "false".
    Верни результат ТОЛЬКО в виде валидного JSON объекта. Никакого Markdown.

    ДАННЫЕ КОМПАНИИ:
    Название: "{title}"
    Основная категория: "{category}"
    Все категории: "{cats_str}"
    Описание: "{description}"
    Ответы владельца: "{owner_replies_str}"
    Отзывы клиентов: "{client_reviews_str}"
    Описания товаров: "{prod_desc_str}"
    FAQ: "{faq_str}"

    ВОПРОСЫ (ключи JSON):
    "PROF-10.6": Есть ли в описании призыв к действию (звоните, сайт)?
    "PROF-10.3": Перечислены ли конкретные услуги, а не общие фразы?
    "CONV-49.1": Есть ли в начале описания сильное УТП?
    "SEO-18.3": Есть ли в описании названия городов/районов (топонимы)?
    "PROF-10.4": Есть ли в описании конкретные факты/преимущества, а не вода?
    "CONV-49.2": Есть ли в описании измеримые показатели (годы, цифры)?
    "PROF-01.2": Является ли название чистым брендом без SEO-спама?
    "REP-31.2": Есть ли в ответах владельца вежливость и корпоративный стиль?
    "CONV-52.2": Снимает ли FAQ реальные страхи клиентов?
    "PROF-02.1": Соответствует ли Основная категория смыслу Описания компании?
    "PROF-03.2": Нет ли в списке Всех категорий "мусорных", не связанных с основным бизнесом?
    "SEO-17.1": Есть ли в Описании целевые ключевые запросы этой ниши?
    "SEO-17.2": Написано ли Описание для людей, без жесткого SEO-переспама?
    "SEO-17.3": Есть ли в Описании LSI-термины (профессиональные слова)?
    "CONV-49.4": Закрывает ли Описание типичные "боли" клиентов этой ниши?
    "SEO-19.1": Вплетает ли владелец в Ответы ключевые коммерческие запросы?
    "SEO-19.2": Упоминают ли клиенты в Отзывах названия услуг?
    "SEO-21.2": Содержат ли Описания товаров развернутые SEO-термины?
    """
    
    try:
        response = ai_model.generate_content(prompt)
        raw_text = response.text
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)
            ai_result = json.loads(clean_json)
            m = {}
            m["PROF-10.6"] = "AI: Нашел призыв к действию (CTA)."
            m["PROF-10.3"] = "AI: Услуги перечислены конкретно."
            m["CONV-49.1"] = "AI: Найдено сильное УТП в первом абзаце."
            m["SEO-18.3"] = "AI: Найдены топонимы в тексте."
            m["PROF-10.4"] = "AI: Найдены конкретные факты/преимущества (без воды)."
            m["CONV-49.2"] = "AI: Найдены числительные и метрики в УТП."
            m["PROF-01.2"] = "AI: Название чистое (без SEO-спама)."
            m["REP-31.2"] = "AI: Ответы владельца выдержаны в Tone of Voice."
            m["CONV-52.2"] = "AI: Блок FAQ закрывает страхи ЦА."
            m["PROF-02.1"] = "AI: Основная категория полностью соответствует Описанию."
            m["PROF-03.2"] = "AI: Мусорных (нерелевантных) категорий не обнаружено."
            m["SEO-17.1"] = "AI: В описании присутствуют целевые ключевые запросы ниши."
            m["SEO-17.2"] = "AI: Описание читаемое, без SEO-переспама ключами."
            m["SEO-17.3"] = "AI: В описании найдена качественная LSI-семантика."
            m["CONV-49.4"] = "AI: Текст релевантен реальным болям ЦА в этой нише."
            m["SEO-19.1"] = "AI: В ответах владельца вшиты коммерческие SEO-ключи."
            m["SEO-19.2"] = "AI: Клиенты органично упоминают услуги в своих отзывах."
            m["SEO-21.2"] = "AI: В карточках товаров есть развернутое SEO-описание."
            
            for code, msg in m.items():
                if ai_result.get(code):
                    scores[code] = True
                    logs.append(f"✅ [{code}] {msg}")
        else:
            ai_critical_error = "Нейросеть не вернула валидный JSON-ответ."
            logs.append(f"⚠️ [AI-Ошибка] {ai_critical_error}")
                
    except Exception as e:
        ai_critical_error = str(e)
        logs.append(f"⚠️ [AI-Ошибка] Сбой Gemini: {e}")
        
    return scores, logs, ai_critical_error


# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ: ЗРЕНИЕ (7 НОВЫХ МЕТРИК) ===
def fetch_image_for_ai(url):
    """Скачивает и сжимает картинку 'на лету' (без сохранения на диск)"""
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            img = Image.open(BytesIO(response.content)).convert('RGB')
            img.thumbnail((800, 800)) # Сжимаем до разумных пределов для скорости
            return img
    except Exception:
        pass
    return None

def calculate_vision_rules(data):
    scores, logs = {}, []
    
    if ai_model is None:
        return scores, logs, "AI Vision отключен (нет модели)."
        
    image_urls = []
    
    # 1. Берем обложку профиля
    cover = str(data.get('coverPhotoUrl') or data.get('coverUrl') or '')
    if cover and 'panorama' not in cover and 'streetview' not in cover:
        image_urls.append(cover)
        
    # 2. Берем до 4 свежих фото из галереи
    photos = get_safe_list(data, ['photos', 'images'])
    for p in photos[:4]:
        p_url = p.get('url') if isinstance(p, dict) else str(p)
        if p_url and 'panorama' not in p_url and 'streetview' not in p_url:
            image_urls.append(p_url)

    if not image_urls:
        logs.append("⚠️ [AI-Vision] Нет доступных фото для визуального анализа. Пропуск.")
        return scores, logs, None

    # ПАРАЛЛЕЛЬНОЕ СКАЧИВАНИЕ (очень быстро)
    with ThreadPoolExecutor(max_workers=5) as executor:
        pil_images = list(filter(None, executor.map(fetch_image_for_ai, image_urls)))
        
    if not pil_images:
        logs.append("⚠️ [AI-Vision] Не удалось скачать фото по ссылкам. Пропуск.")
        return scores, logs, None
        
    prompt = """
    Ты Арт-директор и маркетолог. Изучи эти фотографии компании (первая - это обложка профиля, остальные - фото из галереи).
    Ответь строго в JSON (используй true или false) на 7 вопросов. Никакого Markdown.

    ВОПРОСЫ:
    "CONV-49.3": Есть ли на первой картинке (обложке) читаемый текст, дублирующий оффер или УТП бизнеса?
    "CONT-37.2": Выглядят ли фото как реальные живые кадры компании, а НЕ как пластиковые стоковые фото из интернета?
    "CONT-37.3": Фотографии хорошо освещены (не слишком темные, нормальная контрастность)?
    "CONT-39.1": Есть ли на фото лица людей, сотрудники или живая команда в процессе работы/отдыха?
    "CONT-40.1": Есть ли на фото "бэкстейдж" (виден процесс работы, оказания услуги или производства)?
    "CONT-41.1": Есть ли предметные фотографии (товар, блюдо или результат работы сняты крупно)?
    "CONT-41.2": Высокая ли детализация на предметных фото (фокус на деталях, макро-съемка)?
    """
    
    try:
        # Отправляем промпт + массив картинок одним пакетом
        response = ai_model.generate_content([prompt] + pil_images)
        raw_text = response.text
        
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)
            ai_result = json.loads(clean_json)
            
            m = {}
            m["CONV-49.3"] = "AI Vision: На главной обложке есть текст / визуальный оффер."
            m["CONT-37.2"] = "AI Vision: Фотографии признаны 'своими живыми', а не стоком."
            m["CONT-37.3"] = "AI Vision: Освещенность и контрастность фото в норме."
            m["CONT-39.1"] = "AI Vision: На фотографиях присутствуют люди/команда."
            m["CONT-40.1"] = "AI Vision: Распознан процесс оказания услуги (бэкстейдж)."
            m["CONT-41.1"] = "AI Vision: Присутствуют предметные фотографии товаров."
            m["CONT-41.2"] = "AI Vision: Детализация и крупный план (макро) на высоком уровне."
            
            for code, msg in m.items():
                if ai_result.get(code):
                    scores[code] = True
                    logs.append(f"✅ [{code}] {msg}")
        else:
            logs.append("⚠️ [AI-Vision-Ошибка] Нейросеть не вернула валидный JSON-ответ.")
            
    except Exception as e:
        logs.append(f"⚠️ [AI-Vision-Ошибка] Сбой Gemini Vision: {e}")
        
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
        
    # Смысловой ИИ
    ai_scores, ai_logs, ai_err = calculate_ai_rules(data)
    all_scores.update(ai_scores)
    all_logs.extend(ai_logs)
    if ai_err: global_ai_error = ai_err
        
    # Визуальный ИИ
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

# --- САЙДБАР ---
manual_rules = [r for r in rules_data if r.get('Статус') == "Ручной"]
manual_overrides = {}
with st.sidebar:
    st.header("🎛 Ручная оценка")
    current_prefix = ""
    for r in manual_rules:
        code = str(r.get('Код', '')).strip()
        if not code: continue
        prefix = code.split('-')[0] if '-' in code else "ДРУГОЕ"
        if prefix != current_prefix:
            st.markdown(f"### Блок {prefix}")
            current_prefix = prefix
        name = str(r.get('Критерий', '')).strip()
        max_score = float(r.get('Балл', 1.0))
        if max_score > 0:
            val = st.number_input(f"[{code}] {name}", min_value=0.0, max_value=max_score, value=0.0, step=0.5, help=str(r.get('Инструкция по вычислению', '')))
            manual_overrides[code] = val

# --- ОСНОВНОЙ ЭКРАН ---
st.title("📍 MAP100: AI-Аудитор (Версия 11.0 - 100% Автоматизация!)")

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
                    st.error(f"🚨 КРИТИЧЕСКАЯ ОШИБКА ИИ: Нейросеть не смогла проанализировать данные.\n\nДетали: {ai_error}")
                    send_telegram_alert(f"🚨 Ошибка ИИ в MAP100!\nМодель Gemini упала.\nКомпания: {company_name}\nСсылка: {yandex_url}\nПричина: {ai_error}")
                    
            except Exception as e:
                st.error(f"⚠️ Ошибка работы алгоритма: {e}")
                send_telegram_alert(f"🚨 Критическая ошибка MAP100 (Парсер упал)!\nСсылка: {yandex_url}\nПричина: {e}")
                st.stop()
                
            final_scores_dict = {}
            detailed_results = []
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                max_score = float(r.get('Балл', 0.0))
                status = str(r.get('Статус', 'Заглушка')).strip()
                instruction = str(r.get('Инструкция по вычислению', ''))
                
                current_val = 0.0
                if status == "Python" and python_scores_dict.get(code): 
                    current_val = max_score 
                elif status == "Ручной" and code in manual_overrides: 
                    current_val = min(float(manual_overrides[code]), max_score)
                    
                final_scores_dict[code] = current_val
                
                comment = ""
                if status == "Python":
                    specific_log = None
                    for log in python_logs:
                        if f"[{code}]" in log:
                            parts = log.split("]", 1)
                            if len(parts) > 1:
                                specific_log = parts[1].strip()
                                break
                    if current_val > 0:
                        comment = f"✅ {specific_log}" if specific_log else (f"✅ {instruction}" if instruction else "✅ Выполнено")
                    else:
                        comment = "❌ Не выполнено / Данные отсутствуют"
                elif status == "Ручной":
                    comment = "🧠 Оценено вручную экспертом" if current_val > 0 else "⚪ Не оценивалось (0 баллов)"
                else:
                    comment = "🟡 В разработке (Заглушка)"
                    
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

            # Сохранение в БД
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
            except:
                st.warning("Не удалось сохранить в результаты (проверьте вкладку Results).")

# ==========================================
# 5. СЕРВИСНАЯ ПАНЕЛЬ ДЛЯ РАЗРАБОТЧИКА
# ==========================================
st.divider()
st.subheader("🛠 Сервисная панель разработчика")

if st.button("🪄 1. Разметка статусов (Нажми меня!)"):
    with st.spinner("Расставляю статусы..."):
        try:
            doc = init_google_sheets()
            sheet = doc.worksheet("Rules")
            headers = sheet.row_values(1)
            col_idx = headers.index("Статус") + 1 if "Статус" in headers else len(headers) + 1
            
            records = sheet.get_all_records()
            # ВСЕ 80 МЕТРИК АВТОМАТИЗИРОВАНЫ!
            python_codes = [
                "PROF-01.1", "PROF-03.1", "PROF-05.1", "PROF-05.2", "PROF-07.1", "PROF-08.1", "PROF-11.1", 
                "PROF-11.2", "PROF-11.3", "PROF-11.4", "PROF-11.5", "PROF-12.1", "PROF-13.1", "PROF-13.2", 
                "CONT-36.1", "CONT-36.2", "REP-27.1", "REP-27.2", "REP-28.1", "CONV-48.1", "CONV-50.1", 
                "PROF-04.1", "PROF-04.2", "PROF-10.1", "SEO-18.1", "CONT-44.1", "CONT-42.1", "CONV-51.1", 
                "CONV-47.1", "PROF-15.1", "REP-29.1", "REP-30.1", "REP-30.2", "CONV-52.1", "PROF-07.2", 
                "SEO-18.2", "CONT-43.1", "REP-32.1", "REP-30.3", "REP-31.1", "CONV-53.1", "PROF-14.1",
                "ACT-68.1", "REP-35.1", "ACT-69.1", "PROF-10.6", "PROF-10.3", "CONV-49.1", "SEO-18.3",
                "PROF-10.4", "CONV-49.2", "PROF-01.2", "REP-31.2", "CONV-52.2", "PROF-08.2", "CONV-47.2", 
                "CONV-50.2", "SEO-21.1", "CONV-46.1", "REP-29.2", "REP-32.2", "REP-33.1", "ACT-67.1", 
                "CONV-51.2", "PROF-02.1", "PROF-03.2", "SEO-17.1", "SEO-17.2", "SEO-17.3", 
                "CONV-49.4", "SEO-19.1", "SEO-19.2", "SEO-21.2", 
                # НОВЫЕ 7 ВИЗУАЛЬНЫХ МЕТРИК
                "CONV-49.3", "CONT-37.2", "CONT-37.3", "CONT-39.1", "CONT-40.1", "CONT-41.1", "CONT-41.2"
            ]
            
            cell_list = sheet.range(2, col_idx, len(records) + 1, col_idx)
            for i, row in enumerate(records):
                code = str(row.get('Код', '')).strip()
                if code in python_codes: 
                    cell_list[i].value = "Python"
                else: 
                    cell_list[i].value = "Заглушка"
                    
            sheet.update_cells(cell_list)
            st.success("✅ Статусы обновлены! Абсолютно ВСЕ 80 метрик перенесены в Python! 🎉")
            st.balloons()
        except Exception as e: 
            st.error(f"Ошибка: {e}")
