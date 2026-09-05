import base64
import requests

class DriveManager:
    """
    Менеджер загрузки артефактов аудита на Google Диск
    через шлюз Google Apps Script Web App (в обход квот Service Account).
    """
    def __init__(self, *args, web_app_url=None, pdf_root_id=None, json_root_id=None, letters_root_id=None, **kwargs):
        # Поддержка прямой передачи URL и ID папок или использование боевых констант
        self.web_app_url = web_app_url or "https://script.google.com/macros/s/AKfycbxqgqhSOz6S-qepOiJ0t5r3UizTbuiqPcg4GOqqcOP6cXZ04Ia1PiJtvzV-3Kpm_CxqTg/exec"
        self.pdf_root_id = pdf_root_id or "15kzKEaS76HAhx22FR-BTvifbaecH_wx8"
        self.json_root_id = json_root_id or "1efm3iHSVvUPp50in3tfOGxd0xOACio2E"
        self.letters_root_id = letters_root_id or "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6"

    def upload_file(self, filename: str, content, mime_type: str, root_folder_id: str) -> str:
        if not content:
            raise ValueError(f"Попытка загрузки пустого содержимого для файла: {filename}")

        # Приведение к бинарному формату
        if isinstance(content, str):
            encoded_bytes = content.encode('utf-8')
        elif isinstance(content, bytes):
            encoded_bytes = content
        else:
            encoded_bytes = str(content).encode('utf-8')

        b64_content = base64.b64encode(encoded_bytes).decode('utf-8')

        payload = {
            "folderId": root_folder_id,
            "fileName": filename,
            "fileContent": b64_content,
            "mimeType": mime_type
        }

        try:
            response = requests.post(
                self.web_app_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60
            )
        except requests.exceptions.RequestException as e:
            raise Exception(f"Сетевой сбой при обращении к Google Apps Script: {e}")

        if response.status_code != 200:
            raise Exception(f"Google Apps Script вернул HTTP {response.status_code}: {response.text[:200]}")

        try:
            result = response.json()
        except Exception:
            raise Exception(f"Google Apps Script вернул не-JSON ответ: {response.text[:200]}")

        if isinstance(result, dict) and result.get("status") == "success":
            return result.get("url", "")

        err_msg = result.get("message") if isinstance(result, dict) else response.text[:200]
        raise Exception(f"Отказ Apps Script: {err_msg}")
