import io
from datetime import datetime
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

class DriveManager:
    def __init__(self, credentials):
        self.service = build('drive', 'v3', credentials=credentials)
        
        # Вставьте сюда ID папок из Шага 1
        self.pdf_root_id = "15kzKEaS76HAhx22FR-BTvifbaecH_wx8"
        self.json_root_id = "1efm3iHSVvUPp50in3tfOGxd0xOACio2E"
        self.letters_root_id = "10hP476EXoiPCkRfE9nqc1ZyyTBNvPKR6"

        
        self._folder_cache = {}

    def _get_or_create_monthly_folder(self, parent_folder_id):
        if parent_folder_id in self._folder_cache:
            return self._folder_cache[parent_folder_id]
            
        month_name = datetime.now().strftime("%Y_%m")
        query = f"name='{month_name}' and '{parent_folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
        
        try:
            results = self.service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
        except Exception as e:
            # Выводим ошибку, если Google не дал прочитать папку
            raise Exception(f"Сбой при доступе к папке {parent_folder_id}. Ответ Google: {str(e)}")
        
        files = results.get('files', [])
        
        if files:
            folder_id = files[0].get('id')
        else:
            folder_metadata = {
                'name': month_name,
                'mimeType': 'application/vnd.google-apps.folder',
                'parents': [parent_folder_id]
            }
            try:
                folder = self.service.files().create(body=folder_metadata, fields='id').execute()
                folder_id = folder.get('id')
            except Exception as e:
                # Выводим ошибку, если Google не разрешил создать подпапку
                raise Exception(f"Сбой при создании подпапки {month_name}. Ответ Google: {str(e)}")
            
        self._folder_cache[parent_folder_id] = folder_id
        return folder_id

    def upload_file(self, filename, content, mime_type, root_folder_id):
        try:
            monthly_folder_id = self._get_or_create_monthly_folder(root_folder_id)
            
            if isinstance(content, str):
                content = content.encode('utf-8')
            file_stream = io.BytesIO(content)
            
            media = MediaIoBaseUpload(file_stream, mimetype=mime_type, resumable=False)
            
            file_metadata = {
                'name': filename,
                'parents': [monthly_folder_id]
            }
            
            uploaded_file = self.service.files().create(
                body=file_metadata, 
                media_body=media, 
                fields='id, webViewLink'
            ).execute()
            
            return uploaded_file.get('webViewLink')
        except Exception as e:
            # Выводим ошибку, если сорвалась сама загрузка файла
            raise Exception(f"Сбой при заливке файла '{filename}'. Ответ Google: {str(e)}")
