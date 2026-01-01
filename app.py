from flask import Flask, request, jsonify
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import io, os, datetime, random, json, traceback

# ---------------- LOAD ENV ----------------
load_dotenv()

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive.file'
]

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

COMPONENT_COLUMNS = os.getenv(
    "COMPONENT_COLUMNS",
    "Rent,Maintenance,Water,Electricity,Parking"
).split(",")

# ---------------- FLASK APP ----------------
app = Flask(__name__, static_folder='public', static_url_path='')

# ---------------- GOOGLE AUTH ----------------
def load_credentials():
    token_json = os.getenv("GOOGLE_TOKEN")
    if not token_json:
        raise Exception("GOOGLE_TOKEN not set.")

    return Credentials.from_authorized_user_info(
        json.loads(token_json), SCOPES
    )

creds = load_credentials()
sheet_service = build('sheets', 'v4', credentials=creds)
drive_service = build('drive', 'v3', credentials=creds)

# ---------------- DRIVE HELPERS ----------------
def get_or_create_folder(folder_name, parent_id=None):
    query = (
        f"name='{folder_name}' and "
        f"mimeType='application/vnd.google-apps.folder' and trashed=false"
    )
    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = drive_service.files().list(
        q=query,
        spaces='drive',
        fields='files(id, name)'
    ).execute()

    files = results.get('files', [])
    if files:
        return files[0]['id']

    metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        metadata['parents'] = [parent_id]

    folder = drive_service.files().create(
        body=metadata,
        fields='id'
    ).execute()

    return folder['id']

# ---------------- ROUTES ----------------
@app.route('/')
def index():
    return app.send_static_file('index.html')

@app.route('/submit_invoice', methods=['POST'])
def submit_invoice():
    try:
        print("Submit invoice called")

        ticket_id = 'TKT-' + str(random.randint(1000, 9999))
        timestamp = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        # -------- FORM DATA --------
        rent_start = request.form.get('rent_start', '')
        rent_end = request.form.get('rent_end', '')
        name = request.form.get('name', '')
        mobile = request.form.get('mobile', '')
        email = request.form.get('email', '')
        city = request.form.get('city', '')
        gst_type = request.form.get('gst_type', '')

        # -------- DRIVE FOLDERS --------
        MAIN_FOLDER_NAME = 'Re_Landlord_Invoice'
        city_folder_name = city if city else 'Unknown_City'

        now = datetime.datetime.now()
        month_folder_name = now.strftime('%B_%Y')
        date_folder_name = now.strftime('%Y-%m-%d')

        main_folder_id = get_or_create_folder(MAIN_FOLDER_NAME)
        city_folder_id = get_or_create_folder(city_folder_name, main_folder_id)
        month_folder_id = get_or_create_folder(month_folder_name, city_folder_id)
        date_folder_id = get_or_create_folder(date_folder_name, month_folder_id)

        # -------- INIT FILE LINKS --------
        component_files = {comp: [] for comp in COMPONENT_COLUMNS}

        # -------- FILE UPLOAD --------
        for comp in COMPONENT_COLUMNS:
            files = request.files.getlist(f'{comp.lower()}_files[]')

            for f in files:
                safe_name = secure_filename(f.filename)
                filename = f"{ticket_id}_{safe_name}"

                media = MediaIoBaseUpload(
                    io.BytesIO(f.read()),
                    mimetype=f.mimetype,
                    resumable=False
                )

                uploaded = drive_service.files().create(
                    body={
                        'name': filename,
                        'parents': [date_folder_id]
                    },
                    media_body=media,
                    fields='id, webViewLink'
                ).execute()

                component_files[comp].append(uploaded['webViewLink'])

        # -------- SHEET ROW --------
        row = [
            ticket_id, rent_start, rent_end,
            name, mobile, email, city, gst_type
        ]

        for comp in COMPONENT_COLUMNS:
            row.append(', '.join(component_files[comp]))

        row.append(timestamp)

        sheet_service.spreadsheets().values().append(
            spreadsheetId=SPREADSHEET_ID,
            range='SUBMISSION',
            valueInputOption='RAW',
            body={'values': [row]}
        ).execute()

        return jsonify({'ticket_id': ticket_id})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ---------------- RUN ----------------
if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000)
