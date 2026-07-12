import streamlit as st
import requests
import time
import json
import numpy as np
import re
from datetime import datetime
import google.generativeai as genai
import gspread
from google.oauth2.service_account import Credentials

# ==========================================
# 1. НАСТРОЙКИ
# ==========================================
APIFY_API_TOKEN = st.secrets["APIFY_API_TOKEN"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
APIFY_ACTOR_ID = "zen-studio~yandex-maps-scraper" 

genai.configure(api_key=GEMINI_API_KEY)

# ==========================================
# 2. ФУНКЦИИ И СТРОГИЙ ПАРСЕР ТАБЛИЦЫ
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
    records = doc.worksheet("Rules").get_all_records()
    
    for r in records:
        raw_val = r.get('Балл', 0.0)
        r['DEBUG_RAW_SCORE'] = raw_val # СОХРАНЯЕМ ИСТИННОЕ ЛИЦО GOOGLE ТАБЛИЦЫ ДЛЯ ДЕБАГА
        try:
            if isinstance(raw_val, (int, float)):
                r['Балл'] = float(raw_val)
            else:
                clean_str = str(raw_val).strip().replace(',', '.').replace(' ', '')
                r['Балл'] = float(clean_str) if clean_str else 0.0
        except ValueError:
            r['Балл'] = 0.0
            
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
# 3. АНАЛИЗАТОР PYTHON
# ==========================================
def calculate_python_scores(data):
    scores, details = {}, []
    title = data.get('title') or ''
    description = data.get('description') or ''
    categories = data.get('categories') or []
    phones = data.get('phones') or []
    links = (data.get('links') or []) + (data.get('socials') or [])
    features = data.get('features') or []
    
    if len(title) > 2: scores['PROF-01.1'] = 0.5
    if len(categories) > 1: scores['PROF-03.1'] = 0.5
    if len(phones) > 0: scores['PROF-05.1'] = 1.0
        
    for p in phones:
        if "доб" not in str(p).lower() and len(re.sub(r'\D', '', str(p))) >= 10:
            scores['PROF-05.2'] = 0.5; break

    if len(data.get('schedule') or data.get('workingHours') or []) >= 7: scores['PROF-07.1'] = 1.0
    if len(features) > 0: scores['PROF-08.1'] = 0.5

    desc_len = len(description)
    if desc_len >= 1500: scores['PROF-10.1'] = 0.5

    if data.get('isVerifiedOwner') == True: scores['PROF-12.1'] = 4.0

    photo_count = data.get('photoCount') or data.get('photosCount') or 0
    if photo_count >= 15: scores['CONT-36.1'] = 1.5
    if photo_count >= 30: scores['CONT-36.2'] = 1.0

    products = (data.get('menu') or {}).get('items') or data.get('productCatalog') or []
    if len(products) >= 10:
        scores['PROF-11.1'] = 1.5
        if sum(1 for p in products if p.get('photoUrl') or p.get('imageUrl') or p.get('image')) / len(products) >= 0.8: scores['PROF-11.2'] = 1.0
        if sum(1 for p in products if p.get('price')) / len(products) >= 0.8: scores['PROF-11.3'] = 1.0
        if sum(1 for p in products if len(str(p.get('description') or '')) > 100) / len(products) >= 0.8: scores['PROF-11.4'] = 1.0
        if len(set(p.get('category', {}).get('name') or p.get('category') for p in products if p.get('category'))) >= 2: scores['PROF-11.5'] = 0.5

    links_str, features_str = " ".join(str(l).lower() for l in links), " ".join(str(f).lower() for f in features)
    if any(s in links_str for s in ["vk.com", "youtube", "dzen"]): scores['PROF-13.2'] = 0.5
    if any(s in links_str for s in ["t.me", "tg://", "wa.me", "whatsapp"]): scores['PROF-13.1'] = 0.5
    if any(b in links_str or b in features_str for b in ['yclients', 'dikidi', 'n-go', 'bukza', 'rubitime', 'запись онлайн']): scores['CONV-48.1'] = 3.0 
    if "chat" in features_str or data.get('isChatEnabled') == True: scores['CONV-50.1'] = 1.0
         
    rating = data.get('rating') or 0
    if rating >= 4.8: scores['REP-27.2'] = 2.0; scores['REP-27.1'] = 2.0
    elif rating >= 4.5: scores['REP-27.1'] = 2.0

    if (data.get('ratingsCount') or data.get('reviewsCount') or 0) >= 50: scores['REP-28.1'] = 2.0

    reviews_data = data.get('reviews') or []
    response_times = []
    
    if reviews_data:
        try:
            if (datetime.now() - datetime.strptime(reviews_data[0].get("date", "")[:19], "%Y-%m-%dT%H:%M:%S")).days <= 14: scores['REP-29.1'] = 2.0
        except: pass

    for rev in reviews_data:
        try:
            r_date, c_date = datetime.strptime(rev["date"][:19], "%Y-%m-%dT%H:%M:%S"), datetime.strptime(rev["businessCommentDate"][:19], "%Y-%m-%dT%H:%M:%S")
            response_times.append((c_date - r_date).days)
        except: pass
                
    if response_times and np.median(response_times) <= 3: scores['REP-30.2'] = 2.0

    return sum(scores.values()), details, scores

def trim_for_ai(raw_data):
    trimmed = {
        "title": raw_data.get("title") or "", "description": raw_data.get("description") or "",
        "categories": raw_data.get("categories") or [], "features": list((raw_data.get("features") or {}).keys()),
        "products": [], "reviews": []
    }
    products = (raw_data.get('menu') or {}).get('items') or []
    if products: trimmed["products"] = [p.get("title", "") for p in products[:15]]
    for r in (raw_data.get("reviews") or [])[:10]: trimmed["reviews"].append({"text": r.get("text", ""), "rating": r.get("rating", ""), "owner_reply": r.get("businessComment", "")})
    return trimmed

# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА С ДЕБАГГЕРОМ
# ==========================================
st.set_page_config(page_title="MAP100 | Дебаггер", page_icon="🕵️", layout="wide")

try:
    rules_data = get_rules_from_sheets()
except Exception as e:
    st.error("⚠️ Не удалось загрузить базу правил.")
    st.stop()

st.title("🕵️ MAP100: AI-Аудитор (Версия 4.0 - Дебаггер)")
yandex_url = st.text_input("Ссылка на карточку Яндекс.Бизнеса")

if st.button("🚀 Запустить аудит и диагностику", type="primary"):
    if not yandex_url or ("yandex" not in yandex_url.lower() and "ya.ru" not in yandex_url.lower()):
        st.error("❌ Введите корректную ссылку.")
    else:
        doc = init_google_sheets()
        
        with st.spinner("Анализируем данные..."):
            ai_rules_list = [r for r in rules_data if str(r.get('Код', '')).strip() and 'ИИ' in str(r.get('Как считаем', ''))]
            dynamic_rules = "".join([f"- [{r['Код']}] {r['Критерий']} (Макс {r['Балл']}): {r['Инструкция для ИИ']}\n" for r in ai_rules_list])
            
            raw_yandex_data = fetch_apify_data(yandex_url)
            python_score, python_details, python_scores_dict = calculate_python_scores(raw_yandex_data)
            clean_data = trim_for_ai(raw_yandex_data)
                
            SYSTEM_INSTRUCTION = f"""
            Ты эксперт SEO. Оцени параметры.
            ВЕРНИ ОТВЕТ СТРОГО В ФОРМАТЕ JSON:
            {{
                "company_name": "", 
                "business_niche": "", 
                "ai_criteria_scores": {{"КОД-1": 1.5}},
                "detailed_report": "", 
                "action_plan": []
            }}
            
            ПРАВИЛА ДЛЯ ОЦЕНКИ:
            {dynamic_rules}
            """
            model = genai.GenerativeModel("gemini-flash-latest", system_instruction=SYSTEM_INSTRUCTION, generation_config={"response_mime_type": "application/json", "temperature": 0.1})
            response = model.generate_content(f"Данные:\n{json.dumps(clean_data, ensure_ascii=False)}")
            
            try:
                raw_text = response.text.strip()
                ai_report = json.loads(raw_text[raw_text.find('{'):raw_text.rfind('}')+1]) if '{' in raw_text else json.loads(raw_text)
            except:
                ai_report = {"company_name": "Ошибка ИИ", "ai_criteria_scores": {}}

            # ========================================================
            # ДЕБАГГЕР: СБОР МАКСИМАЛЬНОЙ ИНФОРМАЦИИ
            # ========================================================
            final_scores_dict = {}
            raw_ai_scores = ai_report.get('ai_criteria_scores', {})
            debug_logs = []
            
            for r in rules_data:
                code = str(r.get('Код', '')).strip()
                if not code: continue
                    
                raw_sheet_val = r.get('DEBUG_RAW_SCORE', 'N/A')
                max_score = r.get('Балл', 0.0) 
                
                py_val = python_scores_dict.get(code, "Нет")
                ai_val = raw_ai_scores.get(code, "Нет")
                current_val = 0.0
                source_decision = "Не выполнено (0.0)"
                
                if py_val != "Нет":
                    current_val = min(float(py_val), max_score)
                    source_decision = f"Python (Обрезано: min({py_val}, {max_score}))"
                elif ai_val != "Нет":
                    try:
                        current_val = min(float(ai_val), max_score)
                        source_decision = f"Gemini (Обрезано: min({ai_val}, {max_score}))"
                    except: pass
                    
                final_scores_dict[code] = current_val
                
                debug_logs.append({
                    "Код": code,
                    "Критерий": r.get('Критерий', ''),
                    "Что отдал Google (Сырье)": str(raw_sheet_val),
                    "Лимит в коде": max_score,
                    "ИИ предложил": ai_val,
                    "ИТОГО": current_val,
                    "Вердикт": source_decision
                })
            
            final_total_score = sum(final_scores_dict.values())
            
            # --- ИНТЕРФЕЙС ДЕБАГГЕРА ---
            st.divider()
            st.header("🚨 РЕЖИМ ГЛУБОКОГО ДЕБАГА")
            
            # Поиск аномалий
            anomalies = [d for d in debug_logs if d["ИТОГО"] > 4.0]
            if anomalies:
                st.error(f"⚠️ НАЙДЕНО {len(anomalies)} АНОМАЛИЙ (Балл выше 4.0). Читайте расследование ниже.")
                for a in anomalies:
                    st.warning(f"""
                    **Аномалия в метрике {a['Код']} ({a['Критерий']}): ИТОГО = {a['ИТОГО']}**
                    * **Причина:** Библиотека gspread прочитала из вашей Google Таблицы значение `{a['Что отдал Google (Сырье)']}`.
                    * **Следствие:** Скрипт установил потолок баллов равный `{a['Лимит в коде']}`.
                    * **Как отработала защита:** Нейросеть предложила `{a['ИИ предложил']}`. Функция обрезки сравнила `min({a['ИИ предложил']}, {a['Лимит в коде']})` и, естественно, пропустила аномалию, потому что Лимит в коде оказался огромным.
                    * **Решение:** Проблема на 100% на стороне Google Таблицы (возможно, подключена не та таблица, либо столбец отформатирован так, что Google отдает целые числа вместо дробей).
                    """)
            else:
                st.success("✅ Аномалий не найдено. Все баллы в пределах нормы.")

            with st.expander("🔬 ТЕХНИЧЕСКИЙ ЛОГ КАЖДОЙ ОЦЕНКИ (Таблица диагностики)", expanded=True):
                st.dataframe(debug_logs, use_container_width=True)

            st.divider()
            
            col1, col2 = st.columns([3, 1])
            with col1:
                st.subheader(f"🏢 {ai_report.get('company_name', 'Без названия')}")
            with col2:
                st.metric("Общий балл MAP100", f"{round(final_total_score, 1)} / 100")

            with st.expander("📊 Чистый JSON финальных оценок"):
                st.json(final_scores_dict)
