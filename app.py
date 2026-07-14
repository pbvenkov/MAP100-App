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

# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ (ТЕПЕРЬ 18 МЕТРИК) ===
def calculate_ai_rules(data):
    scores, logs = {}, []
    ai_critical_error = None
    
    if ai_model is None: 
        return scores, logs, "Модель ИИ отключена."
        
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
        for rev in reviews_data[:15]: # Берем 15 последних отзывов для надежности
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
    Верни результат ТОЛЬКО в виде валидного JSON объекта. Никакого Markdown (без ```json).

    ДАННЫЕ КОМПАНИИ:
    Название: "{title}"
    Основная категория: "{category}"
    Все категории: "{cats_str}"
    Описание: "{description}"
    Ответы владельца: "{owner_replies_str}"
    Отзывы клиентов: "{client_reviews_str}"
    Описания товаров: "{prod_desc_str}"
    FAQ: "{faq_str}"

    ВОПРОСЫ:
    "PROF-10.6": Есть ли в описании призыв к действию (звоните, сайт)?
    "PROF-10.3": Перечислены ли конкретные услуги, а не общие фразы?
    "CONV-49.1": Есть ли в начале описания сильное УТП?
    "SEO-18.3": Есть ли в описании названия городов/районов (топонимы)?
    "PROF-10.4": Есть ли в описании конкретные факты/преимущества, а не вода?
    "CONV-49.2": Есть ли в описании измеримые показатели (годы, цифры)?
    "PROF-01.2": Является ли название чистым брендом без SEO-спама (без перечисления услуг/городов)?
    "REP-31.2": Есть ли в ответах владельца вежливость и корпоративный стиль? (Если ответов нет - false).
    "CONV-52.2": Снимает ли FAQ реальные страхи клиентов? (Если FAQ нет - false).
    "PROF-02.1": Соответствует ли Основная категория смыслу Описания компании? (true если да).
    "PROF-03.2": Нет ли в списке Всех категорий "мусорных", не связанных с основным бизнесом? (true если мусора нет).
    "SEO-17.1": Есть ли в Описании целевые ключевые запросы этой ниши (3-5 шт)?
    "SEO-17.2": Написано ли Описание для людей, без жесткого SEO-переспама одним словом? (true если текст читаемый).
    "SEO-17.3": Есть ли в Описании LSI-термины (профессиональные слова, задающие контекст ниши)?
    "CONV-49.4": Закрывает ли Описание или УТП типичные "боли" клиентов этой ниши?
    "SEO-19.1": Вплетает ли владелец в свои Ответы ключевые коммерческие запросы (названия услуг)? (Если ответов нет - false).
    "SEO-19.2": Упоминают ли клиенты в своих Отзывах конкретные названия услуг? (Если отзывов нет - false).
    "SEO-21.2": Содержат ли Описания товаров развернутые SEO/LSI термины? (Если описаний нет - false).
    """
    
    try:
        response = ai_model.generate_content(prompt)
        raw_text = response.text
        
        json_match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)
            ai_result = json.loads(clean_json)
            
            metrics_mapping = {
                "PROF-10.6": "AI: Нашел призыв к действию (CTA).",
                "PROF-10.3": "AI: Услуги перечислены конкретно.",
                "CONV-49.1": "AI: Найдено сильное УТП в первом абзаце.",
                "SEO-18.3": "AI: Найдены топонимы в тексте.",
                "PROF-10.4": "AI: Найдены конкретные факты/преимущества (без воды).",
                "CONV-49.2": "AI: Найдены числительные и метрики в УТП.",
                "PROF-01.2": "AI: Название чистое (без SEO-спама).",
                "REP-31.2": "AI: Ответы владельца выдержаны в Tone of Voice.",
                "CONV-52.2": "AI: Блок FAQ закрывает страхи ЦА.",
                "PROF-02.1": "AI: Основная категория полностью соответствует Описанию.",
                "PROF-03.2": "AI: Мусорных (
