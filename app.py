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

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-1.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден или настроен неверно. AI-функции будут отключены.")
    ai_model = None

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
            if isinstance(raw_val, (int, float)): r['Балл'] = float(raw_val)
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
    if 'error' in run_req: raise Exception(run_req['error'])
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception("⏱ Таймаут парсера.")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
    if status != "SUCCEEDED": raise Exception("Ошибка парсинга Apify.")
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: raise Exception("Нет данных.")
    return dataset[0]

# ==========================================
# 3. МОДУЛЬНАЯ АРХИТЕКТУРА (Безопасная обработка данных)
# ==========================================

def get_safe_list(data, keys):
    """Безопасно извлекает данные в виде списка, даже если пришел словарь или None."""
    result = []
    for k in keys:
        val = data.get(k)
        if isinstance(val, list): result.extend(val)
        elif isinstance(val, dict): result.append(val)
    return result

def calculate_prof_rules(data):
    scores, logs = {}, []
    if data.get('isVerifiedOwner', False):
        scores.update({k: True for k in ['PROF-12.1', 'PROF-01.1', 'PROF-03.1', 'PROF-05.1', 'PROF-07.1']})
        logs.append("✅ [PROF-12.1] Синяя галочка (Верифицирован) подтверждена.")
    else:
        if len(data.get('title', '')) > 2: scores['PROF-01.1'] = True
        if len(data.get('categories') or []) > 0: scores['PROF-03.1'] = True
        if data.get('phones'): scores['PROF-05.1'] = True
        if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = True

    if isinstance(data.get('phones'), list) and any("доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10 for p in data.get('phones')):
        scores['PROF-05.2'] = True
    if data.get('features'): scores['PROF-08.1'] = True
    
    desc = data.get('description') or ''
    if len(desc) > 1500: scores['PROF-10.1'] = True
    
    website = data.get('url') or data.get('website') or ''
    if website: 
        scores['PROF-04.1'] = True
        if "utm_" in str(website).lower(): scores['PROF-04.2'] = True
    if data.get('requisites') or data.get('legalInfo'): 
        scores['PROF-15.1'] = True
        logs.append("✅ [PROF-15.1] Заполнена вкладка с юридическими данными.")

    if any(k in str(data.get('workingHours') or data.get('schedule') or '').lower() for k in ['перерыв', 'special', 'intervals']): 
        scores['PROF-07.2'] = True

    # Безопасный поиск по описанию и особенностям
    desc_and_features = f"{desc} {data.get('features', '')}".lower()
    if re.search(r'(основан[а-я]? в 19\d{2}|основан[а-я]? в 20\d{2}|работает с 19\d{2}|работает с 20\d{2}|since 19\d{2}|since 20\d{2})', desc_and_features):
        scores['PROF-14.1'] = True

    # Безопасный сбор товаров
    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    if len(products) >= 10:
        scores['PROF-11.1'] = True
        if sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image')) / len(products) >= 0.8: scores['PROF-11.2'] = True
        if sum(1 for p in products if p.get('price')) / len(products) >= 0.8: scores['PROF-11.3'] = True
        if sum(1 for p in products if len(str(p.get('description') or '')) > 50) / len(products) >= 0.8: scores['PROF-11.4'] = True
        if len(set(p['category'].get('name') if isinstance(p.get('category'), dict) else p.get('category') for p in products if p.get('category'))) >= 2: scores['PROF-11.5'] = True
            
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
        try:
            if (datetime.now(timezone.utc) - datetime.fromisoformat((reviews[0].get('date') or reviews[0].get('createdAt')).replace('Z', '+00:00'))).days < 14: scores['REP-29.1'] = True
        except: pass
                
        last_20 = reviews[:20]
        replied, total_days, valid_times, unans_neg, ans_pos = 0, 0, 0, 0, 0
        owner_texts = []
        
        with_photo = sum(1 for r in last_20 if r.get('photos') or r.get('images'))
        if last_20 and (with_photo / len(last_20)) >= 0.1: 
            scores['REP-35.1'] = True
            logs.append(f"✅ [REP-35.1] Доля отзывов с фото > 10% ({with_photo} шт).")
        
        for rev in last_20:
            r_rate = rev.get('rating') or 0
            reply = rev.get('reply') or rev.get('ownerAnswer')
            if reply:
                replied += 1
                if isinstance(reply, dict) and reply.get('text'): owner_texts.append(reply.get('text').lower())
                try:
                    r_d = datetime.fromisoformat((rev.get('date') or rev.get('createdAt')).replace('Z', '+00:00'))
                    a_d = datetime.fromisoformat((reply.get('date') or reply.get('createdAt') or reply.get('updatedAt')).replace('Z', '+00:00'))
                    if (a_d - r_d).days >= 0:
                        total_days += (a_d - r_d).days
                        valid_times += 1
                except: pass
            if r_rate <= 3 and not reply: unans_neg += 1
            if r_rate >= 4 and reply: ans_pos += 1
        
        if last_20 and (replied / len(last_20)) >= 0.9: 
            scores['REP-30.1'] = True
            logs.append("✅ [REP-30.1] Владелец ответил на 90%+ отзывов.")
        if valid_times > 0 and (total_days / valid_times) <= 3: 
            scores['REP-30.2'] = True
            logs.append("✅ [REP-30.2] Средняя скорость ответа <= 3 дней.")
        if unans_neg == 0 and last_20: 
            scores['REP-32.1'] = True
            logs.append("✅ [REP-32.1] Нет брошенного негатива.")
        if ans_pos > 0: scores['REP-30.3'] = True
            
        if len(owner_texts) >= 2:
            if not any(len(set(re.findall(r'\w+', t1)) & set(re.findall(r'\w+', t2))) / max(1, len(set(re.findall(r'\w+', t1)) | set(re.findall(r'\w+', t2)))) > 0.8 for t1, t2 in itertools.combinations(owner_texts[:10], 2)):
                scores['REP-31.1'] = True
                logs.append("✅ [REP-31.1] Тексты ответов уникальны (не скопированы).")
        elif len(owner_texts) == 1: scores['REP-31.1'] = True

    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    str_search = f"{data.get('links', '')} {data.get('features', '')} {data.get('socials', '')}".lower()
    
    if any(b in str_search for b in ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн', 'nethouse']):
        scores['CONV-48.1'] = True
        logs.append("✅ [CONV-48.1] Найдена система онлайн-записи.")
        
    if "chat" in str_search or data.get('isChatEnabled'): scores['CONV-50.1'] = True
    if data.get('posts') or data.get('news') or data.get('promos'): scores['CONV-51.1'] = True
    if data.get('actionUrl') or data.get('bookingUrl'): 
        scores['CONV-47.1'] = True
        logs.append("✅ [CONV-47.1] Настроена кнопка действия.")
    if data.get('questionsAndAnswers') or data.get('faq') or data.get('qna'): 
        scores['CONV-52.1'] = True
        logs.append("✅ [CONV-52.1] Заполнен блок FAQ.")
        
    products = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    for p in products:
        if p.get('oldPrice') or p.get('discount') or any(kw in str(p).lower() for kw in ['хит', 'новинка', 'скидка', 'акция']):
            scores['CONV-53.1'] = True
            logs.append("✅ [CONV-53.1] В товарах найдены бейджи (Хит, Скидка).")
            break
    return scores, logs

def calculate_seo_rules(data):
    scores, logs = {}, []
    if len(data.get('address') or '') > 5: scores['SEO-18.1'] = True
    if data.get('serviceArea') or data.get('deliveryArea') or any(k in str(data.get('features') or '').lower() for k in ['выезд', 'доставк', 'зона обслуживани', 'радиус']):
        scores['SEO-18.2'] = True
    return scores, logs

def calculate_act_rules(data):
    scores, logs = {}, []
    fresh, now = False, datetime.now(timezone.utc)
    
    posts = get_safe_list(data, ['posts', 'news', 'promos'])
    for p in posts:
        try:
            if (now - datetime.fromisoformat((p.get('date') or p.get('publishedAt') or p.get('createdAt')).replace('Z', '+00:00'))).days <= 30: fresh = True; break
        except: pass
        
    if not fresh and (data.get('stories') or data.get('storyUrls')): fresh = True
    if fresh: 
        scores['ACT-68.1'] = True
        logs.append("✅ [ACT-68.1] Найдена свежая активность (<30 дней).")
    if data.get('isAdvertiser') or data.get('advertiser'): 
        scores['ACT-69.1'] = True
        logs.append("✅ [ACT-69.1] Карточка оплатила Приоритетное размещение.")
    return scores, logs

# === ИСКУССТВЕННЫЙ ИНТЕЛЛЕКТ ===
def calculate_ai_rules(data):
    scores, logs = {}, []
    if not ai_model: return scores, logs
        
    title = data.get('title', '')
    description = data.get('description', '')
    
    owner_texts = []
    reviews_data = data.get('reviews')
    if isinstance(reviews_data, list):
        for rev in reviews_data[:10]:
            reply = rev.get('reply') or rev.get('ownerAnswer')
            if isinstance(reply, dict) and reply.get('text'): owner_texts.append(reply.get('text'))
    owner_replies_str = " | ".join(owner_texts[:3]) if owner_texts else "Ответов нет"
    
    faq_list = get_safe_list(data, ['questionsAndAnswers', 'faq', 'qna'])
    faq_str = " | ".join([f"Вопрос: {q.get('question')} Ответ: {q.get('answer')}" for q in faq_list[:3]]) if faq_list else "FAQ нет"
        
    prompt = f"""
    Проанализируй текстовые данные компании и ответь на 9 вопросов строго в формате JSON.
    
    ДАННЫЕ ДЛЯ АНАЛИЗА:
    Название: "{title}"
    Описание: "{description}"
    Примеры ответов владельца: "{owner_replies_str}"
    Блок FAQ: "{faq_str}"

    ВОПРОСЫ:
    1. PROF-10.6: Есть ли в описании явный призыв к действию (CTA - звоните, приходите, сайт)?
    2. PROF-10.3: Перечислены ли в описании конкретные услуги, или только общие фразы?
    3. CONV-49.1: Содержит ли первый абзац описания сильное, понятное УТП (чем компания выделяется)?
    4. SEO-18.3: Есть ли в описании названия городов, районов, улиц, метро (топонимы)?
    5. PROF-10.4: Есть ли в описании конкретные преимущества (факты), а не просто клише "качественно", "быстро"?
    6. CONV-49.2: Есть ли в описании числительные и измеримые показатели (годы опыта, сроки в днях, цифры)?
    7. PROF-01.2: Является ли название чистым брендом без SEO-спама? (Верни false, если в названии есть перечисление услуг или городов, например "Ремонт авто Москва Ромашка").
    8. REP-31.2: Прослеживается ли в ответах владельца вежливый корпоративный Tone of Voice (наличие приветствий, уважение)? (Если 'Ответов нет' -> false).
    9. CONV-52.2: Снимают ли вопросы из блока FAQ реальные страхи клиентов (гарантии, возврат, сроки, цены)? (Если 'FAQ нет' -> false).

    Верни ТОЛЬКО валидный JSON объект с булевыми значениями (true или false), без markdown:
    {{
      "PROF-10.6": false, "PROF-10.3": false, "CONV-49.1": false, "SEO-18.3": false,
      "PROF-10.4": false, "CONV-49.2": false, "PROF-01.2": false, "REP-31.2": false, "CONV-52.2": false
    }}
    """
    
    try:
        response = ai_model.generate_content(prompt)
        raw_text = response.text.replace('```json', '').replace('
