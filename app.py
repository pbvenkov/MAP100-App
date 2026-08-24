def fetch_apify_data(yandex_url):
    cleaned_url = normalize_yandex_url(yandex_url)
    
    run_req = requests.post(
        f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/runs?token={APIFY_API_TOKEN}",
        json={
            "startUrls": [{"url": cleaned_url}],
            "maxItems": 1,
            "enrichBusinessData": True,
            "maxPhotos": 80,
            "maxPosts": 30
        },
        timeout=15
    ).json()
    
    if 'error' in run_req: 
        raise Exception(f"Ошибка Apify API: {run_req['error']}")
        
    run_id = run_req['data']['id']
    dataset_id = run_req['data']['defaultDatasetId']
    status, retries = "RUNNING", 0
    
    while status not in ["SUCCEEDED", "FAILED", "ABORTED"]:
        if retries >= 35: 
            raise Exception("Таймаут сбора данных. Яндекс долго отвечает.")
        time.sleep(4)
        status_req = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}?token={APIFY_API_TOKEN}", timeout=10).json()
        status = status_req['data']['status']
        retries += 1
        
    if status != "SUCCEEDED": 
        raise Exception(f"Парсер завершился со статусом {status}.")
        
    dataset = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items?token={APIFY_API_TOKEN}", timeout=15).json()
    
    if not isinstance(dataset, list) or len(dataset) == 0:
        raise Exception(f"Яндекс не вернул данные по адресу: {cleaned_url}")
        
    first_item = dataset[0]
    if not isinstance(first_item, dict):
        raise Exception(f"Некорректный формат данных ответа.")
        
    # Извлекаем название из любого доступного поля
    resolved_title = first_item.get('title') or first_item.get('name') or first_item.get('companyName') or first_item.get('header')
    
    # Если названия нет, но есть адрес или телефон — карточка живая
    if not resolved_title:
        if not (first_item.get('address') or first_item.get('phones') or first_item.get('url')):
            raise Exception(f"Яндекс вернул пустую карточку по адресу: {cleaned_url}")
        resolved_title = "Организация"
        
    first_item['title'] = resolved_title
    return first_item
