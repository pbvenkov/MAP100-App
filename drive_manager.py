import base64
import requests

class DriveManager:
    def __init__(self, credentials=None):
        # Пароли от сервисного аккаунта нам больше не нужны, мы их игнорируем!
        
        # 1. ВСТАВЬТЕ СЮДА ССЫЛКУ ИЗ GOOGLE APPS SCRIPT (которую вы скопировали на Шаге 2)
        self.web_app_url = "https://script.google.com/macros/s/AKfycbxqgqhSOz6S-qepOiJ0t5r3UizTbuiqPcg4GOqqcOP6cXZ04Ia1PiJtvzV-3Kpm_CxqTg/exec"
        
        # 2. ВСТАВЬТЕ СЮДА ВАШИ ID ПАПОК
        self.pdf_root_id = "15kzKEaS76HAhx22FR-BTvifbaecH_wx8"
        self.json_root_id = "1efm3iHSVvUPp50in3tfOGxd0xOACio2E"
        self.letters_root_id = "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6"

    def upload_file(self, filename, content, mime_type, root_folder_id):
        try:
            # Конвертируем контент в base64 для надежной передачи через интернет
            if isinstance(content, str):
                content = content.encode('utf-8')
            
            b64_content = base64.b64encode(content).decode('utf-8')
            
            payload = {
                "folderId": root_folder_id,
                "fileName": filename,
                "fileContent": b64_content,
                "mimeType": mime_type
            }
            
            # Отправляем файл вашему скрипту-приемнику
            response = requests.post(self.web_app_url, json=payload, timeout=60)
            result = response.json()
            
            if result.get("status") == "success":
                return result.get("url")
            else:
                raise Exception(result.get("message"))
                
        except Exception as e:
            raise Exception(f"Отказ Apps Script: {str(e)}")
