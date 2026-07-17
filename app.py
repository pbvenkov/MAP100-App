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

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from PIL import Image

# ==========================================
# 1. НАСТРОЙКИ СЕКРЕТОВ И API
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    ai_model = genai.GenerativeModel('gemini-3.5-flash') 
except Exception as e:
    st.warning("⚠️ Ключ Gemini API не найден. AI отключен.")
    ai_model = None

def send_telegram_alert(message):
    token = st.secrets.get("TELEGRAM_BOT_TOKEN")
    chat_id = st.secrets.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message}, timeout=5)
        except: pass

# ==========================================
# 1.5. ИИ-РОУТЕР НИШ И ЭКОНОМИКА
# ==========================================
NICHE_ECONOMICS = {
    "HORECA": {"leads": 300, "check": 2500},
    "B2B_PRODUCTION": {"leads": 20, "check": 100000},
    "RETAIL": {"leads": 400, "check": 1500},
    "AUTO": {"leads": 150, "check": 8000},
    "SERVICES": {"leads": 100, "check": 5000},
    "BEAUTY_MEDICAL": {"leads": 150, "check": 4000},
    "OTHER": {"leads": 100, "check": 3000}
}

def determine_niche(title, category):
    if not ai_model: return "OTHER"
    prompt = f"""
    Определи бизнес по названию "{title}" и категории "{category}".
    ВНИМАНИЕ: Если в категории есть слова "стоматология", "клиника", "медицина", "красота", "салон" - это СТРОГО BEAUTY_MEDICAL.
    
    Выбери ОДИН наиболее подходящий ключ из списка:
    - HORECA (Рестораны, кафе, бары, доставка еды)
    - B2B_PRODUCTION (Заводы, склады, опт, строительство, производство)
    - RETAIL (Магазины одежды, продуктов, ПВЗ, цветы, розница)
    - AUTO (СТО, шиномонтаж, мойки, детейлинг)
    - SERVICES (Клининг, юристы, фотографы, ремонт техники, выездные услуги)
    - BEAUTY_MEDICAL (Салоны красоты, барбершопы, клиники, стоматологии, спа, фитнес)
    - OTHER (Если ничего не подходит)
    
    Верни ТОЛЬКО ОДНО СЛОВО - ключ на английском.
    """
    try:
        key = ai_model.generate_content(prompt).text.strip().upper()
        valid_keys = ["BEAUTY_MEDICAL", "HORECA", "B2B_PRODUCTION", "RETAIL", "AUTO", "SERVICES", "OTHER"]
        for v in valid_keys:
            if v in key: return v
        return "OTHER"
    except: return "OTHER"

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
    except: st.stop()

def get_rules_from_sheets():
    doc = init_google_sheets()
    records = doc.worksheet("Rules").get_all_records(value_render_option='UNFORMATTED_VALUE')
    for r in records:
        r['Статус'] = str(r.get('Статус', 'Заглушка')).strip()
    return records

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_apify_data(yandex_url):
    run_url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}"
    run_req = requests.post(run_url, json={"startUrls": [{"url": yandex_url}], "maxItems": 1}).json()
    run_id, dataset_id = run_req['data']['id'], run_req['data']['defaultDatasetId']
    
    status, retries = "RUNNING", 0
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 30: raise Exception("Таймаут парсера.")
        time.sleep(5)
        status = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}").json()['data']['status']
        retries += 1
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}").json()
    if not dataset: raise Exception("Парсер вернул пустой ответ.")
    return dataset[0]

# ==========================================
# 3. АЛГОРИТМЫ ОЦЕНКИ
# ==========================================
def get_safe_list(data, keys):
    res = []
    for k in keys:
        if isinstance(data.get(k), list): res.extend(data[k])
        elif isinstance(data.get(k), dict): res.append(data[k])
    return res

def calculate_prof_rules(data):
    scores, logs = {}, []
    if data.get('isVerifiedOwner'):
        for k in ['PROF-12.1', 'PROF-01.1', 'PROF-03.1', 'PROF-05.1', 'PROF-07.1']: scores[k] = True
    else:
        if len(data.get('title', '')) > 2: scores['PROF-01.1'] = True
        if data.get('categories'): scores['PROF-03.1'] = True
        if data.get('phones'): scores['PROF-05.1'] = True
        if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = True

    if isinstance(data.get('phones'), list):
        for p in data['phones']:
            if "доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10:
                scores['PROF-05.2'] = True
                break
                
    feat = data.get('features') or []
    if feat: scores['PROF-08.1'] = True
    if len(feat) >= 5: scores['PROF-08.2'] = True
    if len(data.get('description', '')) > 1500: scores['PROF-10.1'] = True
    
    url = str(data.get('url') or data.get('website') or '')
    if url: 
        scores['PROF-04.1'] = True
        if "utm_" in url.lower(): scores['PROF-04.2'] = True
            
    if data.get('requisites') or data.get('legalInfo'): scores['PROF-15.1'] = True
    if any(k in str(data.get('workingHours', '')).lower() for k in ['перерыв', 'special']): scores['PROF-07.2'] = True
    if re.search(r'(в 19\d{2}|в 20\d{2}|с 19\d{2}|с 20\d{2}|since)', f"{data.get('description','')} {feat}".lower()): scores['PROF-14.1'] = True

    prods = get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog'])
    valid_prods = [p for p in prods if isinstance(p, dict)]
    if len(valid_prods) >= 10:
        scores['PROF-11.1'] = True
        if sum(1 for p in valid_prods if p.get('photoUrl') or p.get('imageUrl') or p.get('image')) / len(valid_prods) >= 0.8: scores['PROF-11.2'] = True
        if sum(1 for p in valid_prods if p.get('price')) / len(valid_prods) >= 0.8: scores['PROF-11.3'] = True
        if sum(1 for p in valid_prods if len(str(p.get('description') or '')) > 50) / len(valid_prods) >= 0.8: scores['PROF-11.4'] = True
        c_set = set(p.get('category', {}).get('name') if isinstance(p.get('category'), dict) else p.get('category') for p in valid_prods)
        if len(c_set) >= 2: scores['PROF-11.5'] = True
            
    raw_data_str = json.dumps(data).lower()
    if any(s in raw_data_str for s in ["t.me", "wa.me", "whatsapp", "viber", "tg://"]): 
        scores['PROF-13.1'] = True
    if any(s in raw_data_str for s in ["vk.com", "youtube", "dzen", "instagram", "inst:"]): 
        scores['PROF-13.2'] = True

    return scores, logs

def calculate_cont_rules(data):
    scores, logs = {}, []
    pc = data.get('photoCount') or data.get('photosCount') or 0
    if pc >= 15: scores['CONT-36.1'] = True
    if pc >= 30: scores['CONT-36.2'] = True
    
    if data.get('stories') or data.get('storyUrls'): scores['CONT-44.1'] = True
    if data.get('panoramaUrl') or data.get('panoramas') or data.get('videos'): scores['CONT-42.1'] = True
        
    for p in get_safe_list(data, ['photos', 'images']):
        if isinstance(p, dict):
            keywords = ['внутри', 'интерьер', 'interior', 'inside', 'indoor', 'залы', 'зал', 'hall', 'room']
            if any(kw in str(p).lower() for kw in keywords):
                scores['CONT-43.1'] = True
                break
                
    return scores, logs

def calculate_rep_rules(data):
    scores, logs = {}, []
    rating = data.get('rating') or 0.0
    if rating >= 4.5: scores['REP-27.1'] = True
    if rating >= 4.8: scores['REP-27.2'] = True
    if (data.get('reviewsCount') or data.get('ratingsCount') or 0) >= 50: scores['REP-28.1'] = True
    
    reviews = [r for r in data.get('reviews', []) if isinstance(r, dict)]
    if reviews:
        dates = []
        for r in reviews[:20]:
            try: dates.append(datetime.fromisoformat(str(r.get('date') or r.get('createdAt')).replace('Z', '+00:00')))
            except: pass
        if dates and (datetime.now(timezone.utc) - dates[0]).days < 14: scores['REP-29.1'] = True
        if len(dates) >= 3:
            diffs = [(dates[i] - dates[i+1]).days for i in range(len(dates)-1)]
            if diffs and (sum(d == 0 for d in diffs) / len(diffs)) < 0.3: scores['REP-29.2'] = True
                
        replied, td, vt, unans_neg, ans_pos = 0, 0, 0, 0, 0
        ow_txt = []
        l20 = reviews[:20]
        if l20 and sum(1 for r in l20 if r.get('photos')) / len(l20) >= 0.1: scores['REP-35.1'] = True
        
        for r in l20:
            rate, rep = r.get('rating') or 0, r.get('reply') or r.get('ownerAnswer')
            if isinstance(rep, dict):
                replied += 1
                if rep.get('text'): ow_txt.append(str(rep.get('text')).lower())
                try:
                    rd = datetime.fromisoformat(str(r.get('date') or r.get('createdAt')).replace('Z', '+00:00'))
                    ad = datetime.fromisoformat(str(rep.get('date') or rep.get('createdAt') or rep.get('updatedAt')).replace('Z', '+00:00'))
                    if (ad - rd).days >= 0: td += (ad - rd).days; vt += 1
                except: pass
            if rate <= 3 and not rep: unans_neg += 1
            if rate >= 4 and rep: ans_pos += 1
        
        if l20 and (replied / len(l20)) >= 0.9: scores['REP-30.1'] = True
        if vt > 0 and (td / vt) <= 3: scores['REP-30.2'] = True
        if unans_neg == 0 and l20: scores['REP-32.1'] = True
        if ans_pos > 0: scores['REP-30.3'] = True
            
        if len(ow_txt) >= 2:
            templ = False
            for t1, t2 in itertools.combinations(ow_txt[:10], 2):
                w1, w2 = set(re.findall(r'\w+', t1)), set(re.findall(r'\w+', t2))
                if (len(w1 & w2) / max(1, len(w1 | w2))) > 0.8: templ = True; break
            if not templ: scores['REP-31.1'] = True
        elif len(ow_txt) == 1: scores['REP-31.1'] = True

        if ow_txt:
            if not any(w in t for t in ow_txt for w in ['вранье', 'ложь', 'суд', 'неадекват']): scores['REP-32.2'] = True
            if any(w in t for t in ow_txt for w in ['не были', 'не находим', 'уточните']): scores['REP-33.1'] = True
    return scores, logs

def calculate_conv_rules(data):
    scores, logs = {}, []
    s_str = f"{data.get('links', '')} {data.get('features', '')} {data.get('socials', '')}".lower()
    bsys = ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'leclick', 'tomesto', 'restoclub', 'prodoctorov', 'docdoc', 'sberhealth']
    
    if any(b in s_str for b in bsys): scores['CONV-48.1'] = True
    if "chat" in s_str or data.get('isChatEnabled'): scores['CONV-50.1'] = True
    if data.get('isChatEnabled') and (data.get('isAdvertiser') or "бот" in s_str): scores['CONV-50.2'] = True
    if data.get('posts') or data.get('news') or data.get('promos'): scores['CONV-51.1'] = True
    
    au = str(data.get('actionUrl') or data.get('bookingUrl') or '').lower()
    if au: 
        scores['CONV-47.1'] = True
        if any(b in au for b in bsys + ['whatsapp', 't.me']): scores['CONV-47.2'] = True

    c = str(data.get('coverPhotoUrl') or data.get('coverUrl') or '').lower()
    if c and 'panorama' not in c: scores['CONV-46.1'] = True
    if data.get('questionsAndAnswers') or data.get('faq') or data.get('qna'): scores['CONV-52.1'] = True
        
    if get_safe_list(data, ['promos']): scores['CONV-51.2'] = True
    else:
        for p in get_safe_list(data, ['posts', 'news']):
            if isinstance(p, dict) and any(w in str(p.get('text', '')).lower() for w in ['акция', 'скидка']):
                scores['CONV-51.2'] = True; break

    for p in get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog']):
        if isinstance(p, dict) and (p.get('oldPrice') or p.get('discount') or any(kw in str(p.get('name', '')).lower() for kw in ['хит', 'скидка'])):
            scores['CONV-53.1'] = True; break
    return scores, logs

def calculate_seo_rules(data):
    scores, logs = {}, []
    if len(data.get('address') or '') > 5: scores['SEO-18.1'] = True
    f = str(data.get('features') or '').lower()
    if data.get('serviceArea') or any(k in f for k in ['выезд', 'доставк', 'зона']): scores['SEO-18.2'] = True
    prods = [p for p in get_safe_list(data.get('menu') or {}, ['items']) + get_safe_list(data, ['productCatalog']) if isinstance(p, dict)]
    if prods and (sum(len(str(p.get('name', '')).split()) for p in prods) / len(prods)) >= 2.0: scores['SEO-21.1'] = True
    return scores, logs

def calculate_act_rules(data):
    scores, logs = {}, []
    f, n, pwi = False, datetime.now(timezone.utc), False
    for p in [x for x in get_safe_list(data, ['posts', 'news', 'promos']) if isinstance(x, dict)]:
        try:
            pd = datetime.fromisoformat(str(p.get('date') or p.get('publishedAt') or p.get('createdAt')).replace('Z', '+00:00'))
            if (n - pd).days <= 30: 
                f = True
                if p.get('imageUrl') or p.get('images'): pwi = True
        except: pass
    if not f and (data.get('stories') or data.get('storyUrls')): f = True
    if f: scores['ACT-68.1'] = True
    if pwi or data.get('stories') or data.get('storyUrls'): scores['ACT-67.1'] = True
    if data.get('isAdvertiser') or data.get('advertiser'): scores['ACT-69.1'] = True
    return scores, logs

def calculate_ai_rules(data):
    scores, logs = {}, []
    if not ai_model: return scores, logs, None
    c_list = data.get('categories', [])
    cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
    
    pr = f"""Анализ ниши ({data.get('title')}, {cat}). Ответь JSON (true/false) на: PROF-10.6, PROF-10.3, CONV-49.1, SEO-18.3, PROF-10.4, CONV-49.2, PROF-01.2, REP-31.2, CONV-52.2, PROF-02.1, PROF-03.2, SEO-17.1, SEO-17.2, SEO-17.3, CONV-49.4, SEO-19.1, SEO-19.2, SEO-21.2. Описание: {data.get('description', '')[:500]}"""
    try:
        res = json.loads(re.search(r'\{.*\}', ai_model.generate_content(pr).text, re.DOTALL).group(0))
        for k in res: 
            if res[k]: scores[k] = True
    except: pass
    return scores, logs, None

def fetch_img(url):
    try:
        r = requests.get(url if url.startswith('http') else f"https:{url}", timeout=3)
        if r.status_code == 200:
            i = Image.open(BytesIO(r.content)).convert('RGB'); i.thumbnail((600,600)); return i
    except: pass
    return None

def calculate_vision_rules(data):
    scores, logs = {}, []
    if not ai_model: return scores, logs, None
    urls = [str(data.get('coverUrl') or '')] + [p.get('url') for p in get_safe_list(data, ['photos', 'images'])[:4] if isinstance(p, dict)]
    urls = [u for u in urls if u and 'panorama' not in u]
    if not urls:
        urls = list(set([u for u in re.findall(r'https?://[^\s<>"]+?\.jpg|https?://avatars\.mds\.yandex\.net/[^\s<>"]+', json.dumps(data)) if 'panorama' not in u]))[:5]
    if not urls: return scores, logs, None
    with ThreadPoolExecutor(5) as ex: imgs = list(filter(None, ex.map(fetch_img, urls)))
    if not imgs: return scores, logs, None
    try:
        pr = """Анализ фото. Верни JSON (true/false) на: CONV-49.3, CONT-37.2, CONT-37.3, CONT-39.1, CONT-40.1, CONT-41.1, CONT-41.2."""
        res = json.loads(re.search(r'\{.*\}', ai_model.generate_content([pr] + imgs).text, re.DOTALL).group(0))
        for k in res: 
            if res[k]: scores[k] = True
    except: pass
    return scores, logs, None

# ==========================================
# 4. СБОРКА И ИНТЕРФЕЙС
# ==========================================
st.set_page_config(page_title="MAP100 | Нейро-Аудитор", layout="wide", page_icon="📈")

rules_data = get_rules_from_sheets()
with st.sidebar: st.write("✅ База данных подключена напрямую. Управление весами в Google Sheets.")
st.title("📍 MAP100: AI-Аудитор (Версия 11.7 - Патч Стоматологий)")

url = st.text_input("Ссылка на Яндекс.Бизнес")

if st.button("🚀 Запустить аудит", type="primary"):
    if "yandex" not in url.lower(): st.error("❌ Неверная ссылка.")
    else:
        with st.spinner("Анализ данных, маршрутизация и расчет экономики..."):
            data = fetch_apify_data(url)
            title = data.get('title', 'Без названия')
            c_list = data.get('categories', [])
            
            # ПАТЧ: Универсальное извлечение категории
            cat = c_list[0].get('name', '') if c_list and isinstance(c_list[0], dict) else (str(c_list[0]) if c_list else '')
            
            # 1. ОПРЕДЕЛЯЕМ НИШУ
            niche_key = determine_niche(title, cat)
            
            # 2. РАСЧЕТ МЕТРИК
            raw_scores = {}
            for f in [calculate_prof_rules, calculate_cont_rules, calculate_rep_rules, calculate_conv_rules, calculate_seo_rules, calculate_act_rules, calculate_ai_rules, calculate_vision_rules]:
                sc, _, _ = f(data) if f.__name__ in ['calculate_ai_rules', 'calculate_vision_rules'] else (*f(data), None)
                raw_scores.update(sc)
            
            # 3. ПОДСЧЕТ ИЗ ВЕРНОГО СТОЛБЦА
            final_scores = {}
            results = []
            final_total_score = 0.0
            
            target_column = niche_key if (rules_data and niche_key in rules_data[0]) else 'Балл'
            if niche_key in ['BEAUTY_MEDICAL', 'OTHER']:
                target_column = 'Балл'
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                name = str(r.get('Критерий', '')).strip()
                
                try: max_s = float(str(r.get(target_column, r.get('Балл', 0.0))).strip().replace(',', '.') or 0.0)
                except: max_s = float(r.get('Балл', 0.0))
                
                if max_s == 0.0:
                    final_scores[code] = 0.0
                    results.append({"Код": code, "Критерий": name, "Балл": 0.0, "Макс": 0.0, "Комментарий": f"🟢 Не требуется в нише {niche_key}"})
                else:
                    val = max_s if raw_scores.get(code) else 0.0
                    final_total_score += val
                    final_scores[code] = val
                    comm = "✅ Выполнено" if val > 0 else "❌ Не выполнено"
                    results.append({"Код": code, "Критерий": name, "Балл": val, "Макс": max_s, "Комментарий": comm})
            
            # 4. РАСЧЕТ УПУЩЕННОЙ ВЫРУЧКИ (ЭКОНОМИКА)
            eco = NICHE_ECONOMICS.get(niche_key, NICHE_ECONOMICS["OTHER"])
            potential_leads = eco["leads"]
            avg_check = eco["check"]
            
            lost_percentage = max(0.0, 100.0 - final_total_score) / 100.0
            lost_revenue = int(potential_leads * lost_percentage * avg_check)
            formatted_loss = f"{lost_revenue:,}".replace(',', ' ')
            
            st.divider()
            
            col1, col2, col3 = st.columns([2, 1, 1.2])
            with col1: 
                st.subheader(f"🏢 {title}")
                st.caption(f"🧠 Ниша бизнеса: **{niche_key}**")
            with col2: 
                color = "normal" if final_total_score >= 80 else ("off" if final_total_score >= 50 else "inverse")
                st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100", delta_color=color)
            with col3:
                st.metric("Упущенная выручка (мес)", f"- {formatted_loss} ₽", delta="Недополученный трафик", delta_color="inverse")
            
            st.error(f"""
            💸 **Откуда эта цифра?**  
            Ваша карточка отрабатывает только на **{round(final_total_score, 1)}%** от своего потенциала. 
            Мы рассчитали потери на основе средних отраслевых показателей для ниши **{niche_key}** (Потенциал: ~{potential_leads} горячих лидов/мес, Средний чек: ~{avg_check:,} ₽). Вы теряете около **{int(lost_percentage*100)}%** клиентов, которые уходят к конкурентам из-за недооформленной карточки и пробелов в репутации.
            
            🚀 **Если вы хотите точнее узнать сумму потерь для ВАШЕГО бизнеса с учетом ваших реальных чеков и получить пошаговый план возврата этих денег — [оставьте заявку на бесплатный разбор с экспертом](#).**
            """)
            
            st.divider()
            st.dataframe(pd.DataFrame(results), hide_index=True, use_container_width=True)

            try:
                results_sheet = doc.worksheet("Results")
                headers = results_sheet.row_values(1)
                if not headers: headers = ["Дата", "Ссылка", "Компания", "Общий балл", "Упущенная выручка"]
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
                    elif h == "Ссылка": row_data.append(url)
                    elif h == "Компания": row_data.append(title)
                    elif h == "Общий балл": row_data.append(final_total_score)
                    elif h == "Упущенная выручка": row_data.append(lost_revenue)
                    else: row_data.append(final_scores_dict.get(h, 0.0))
                results_sheet.append_row(row_data)
            except: pass
