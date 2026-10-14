import os
import sys
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
from dotenv import load_dotenv, set_key

# Cargar configuración actual
ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH, override=True)

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = "http://localhost:5489/api/auth/google/callback"
PORT = 5489

if not CLIENT_ID or not CLIENT_SECRET:
    print("Error: GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET deben estar definidos en el archivo .env")
    sys.exit(1)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

auth_code = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed_url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_url.query)

        if "code" in query:
            auth_code = query["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <html>
            <body style="font-family: Arial, sans-serif; text-align: center; padding-top: 50px;">
                <h1 style="color: #2e7d32;">¡Autenticación Exitosa con tu Cuenta!</h1>
                <p>El código de autorización fue recibido correctamente.</p>
                <p>Puedes cerrar esta pestaña y regresar a la terminal.</p>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Error: No se recibio el codigo de autorizacion.")

    def log_message(self, format, *args):
        # Silenciar logs HTTP estándar en consola
        return


def exchange_code_for_token(code: str):
    print("\n[INFO] Canjeando código con Google por el nuevo Refresh Token...")
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }

    resp = requests.post(token_url, data=payload)
    data = resp.json()

    if "error" in data:
        print(f"\n[ERROR] Google rechazó el código: {data.get('error')} - {data.get('error_description')}")
        sys.exit(1)

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("\n[ALERTA] Google devolvió un access token pero no un nuevo refresh token.")
        print("Esto suele ocurrir si ya habías autorizado antes sin revocar.")
        print("Respuesta completa de Google:", data)
        return

    print("\n========================================================")
    print("¡NUEVO REFRESH TOKEN OBTENIDO CON ÉXITO PARA TU CUENTA!")
    print("========================================================")
    print(refresh_token)

    # Actualizar archivo .env automáticamente
    set_key(ENV_PATH, "GOOGLE_CLIENT_ID", CLIENT_ID)
    set_key(ENV_PATH, "GOOGLE_CLIENT_SECRET", CLIENT_SECRET)
    set_key(ENV_PATH, "GOOGLE_REFRESH_TOKEN", refresh_token)
    set_key(ENV_PATH, "GOOGLE_SERVICE_ACCOUNT_FILE", "")

    print(f"\n-> Archivo {ENV_PATH} actualizado automáticamente.")
    print("-> Ya puedes ejecutar: .venv/bin/python main.py --dry-run\n")


def main():
    print("========================================================")
    print(" AUTENTICACIÓN GOOGLE DRIVE CON TU CUENTA PERSONAL")
    print("========================================================")

    scope_str = " ".join(SCOPES)
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": scope_str,
        "access_type": "offline",
        "prompt": "consent"
    }

    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    print("\n1. Abre este enlace en tu navegador con TU cuenta de Google:\n")
    print(auth_url)
    print("\n2. Inicia sesión y haz clic en 'Continuar' / 'Permitir'.")
    print(f"3. Esperando respuesta en {REDIRECT_URI} ...")
    print("   (Presiona Ctrl+C si prefieres cancelar o pegar el código manualmente)\n")

    server = HTTPServer(("0.0.0.0", PORT), OAuthCallbackHandler)

    try:
        while not auth_code:
            server.handle_request()

        if auth_code:
            exchange_code_for_token(auth_code)

    except KeyboardInterrupt:
        print("\n\nOperación cancelada por el usuario.")
        code_input = input("Si tienes el código copiado de la barra de direcciones, pégalo aquí (o Enter para salir): ").strip()
        if code_input:
            exchange_code_for_token(code_input)


if __name__ == "__main__":
    main()
