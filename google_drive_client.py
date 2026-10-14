import io
import os
import logging
from typing import List, Dict, Optional
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from config import config

logger = logging.getLogger("RPA.GoogleDrive")

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]


def get_google_credentials():
    """
    Obtiene las credenciales de Google Workspace.
    Soporta:
      1. OAuth2 con refresh token (como en estudios-errados)
      2. Service Account JSON file
    """
    # 1. Intentar Service Account si se definió la ruta
    if config.GOOGLE_SERVICE_ACCOUNT_FILE and os.path.exists(config.GOOGLE_SERVICE_ACCOUNT_FILE):
        logger.info(f"Usando autenticación con Service Account: {config.GOOGLE_SERVICE_ACCOUNT_FILE}")
        return service_account.Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )

    # 2. Intentar OAuth2 con refresh token
    if config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and config.GOOGLE_REFRESH_TOKEN:
        logger.info("Usando autenticación OAuth2 con Client ID y Refresh Token")
        creds = Credentials(
            token=None,
            refresh_token=config.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.GOOGLE_CLIENT_ID,
            client_secret=config.GOOGLE_CLIENT_SECRET,
            scopes=SCOPES
        )
        return creds

    raise ValueError(
        "No se encontraron credenciales de Google válidas. "
        "Define (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REFRESH_TOKEN) o GOOGLE_SERVICE_ACCOUNT_FILE en el archivo .env"
    )


def get_drive_service():
    """Construye y retorna el cliente de la API de Google Drive v3."""
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds)


def list_subfolders(parent_folder_id: str) -> List[Dict]:
    """Lista las subcarpetas contenidas dentro de parent_folder_id."""
    service = get_drive_service()
    q = f"'{parent_folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id, name, modifiedTime, createdTime)",
        pageSize=100
    ).execute()
    return results.get("files", [])


def list_files_in_drive(folder_id: Optional[str] = None, pattern: str = "MATRIZ 3100") -> List[Dict]:
    """
    Lista los archivos de Drive que coincidan con el patrón (ej. 'MATRIZ 3100').
    Si folder_id está definido, busca dentro de esa carpeta.
    """
    service = get_drive_service()
    query_parts = ["trashed = false"]

    if folder_id:
        query_parts.append(f"'{folder_id}' in parents")
    
    if pattern:
        query_parts.append(f"name contains '{pattern}'")

    q = " and ".join(query_parts)
    logger.info(f"Consultando Google Drive con query: {q}")

    results = service.files().list(
        q=q,
        spaces="drive",
        fields="files(id, name, mimeType, modifiedTime, size)",
        pageSize=100
    ).execute()

    files = results.get("files", [])
    logger.info(f"Se encontraron {len(files)} archivos en Google Drive.")
    return files



def download_file_to_bytes(file_id: str, mime_type: str) -> io.BytesIO:
    """
    Descarga el archivo desde Google Drive a un buffer en memoria (io.BytesIO).
    Maneja tanto Google Sheets nativos (exportando a .xlsx) como archivos .xlsx existentes.
    """
    service = get_drive_service()
    buffer = io.BytesIO()

    # Si es hoja nativa de Google Sheets, exportar a XLSX
    if mime_type == "application/vnd.google-apps.spreadsheet":
        logger.info(f"Exportando Google Sheet (ID: {file_id}) a formato Excel XLSX...")
        request = service.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        # Descarga directa de archivo binario (Excel .xlsx)
        logger.info(f"Descargando archivo binario (ID: {file_id}, mime: {mime_type})...")
        request = service.files().get_media(fileId=file_id)

    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        if status:
            logger.debug(f"Descargando {int(status.progress() * 100)}%")

    buffer.seek(0)
    return buffer
