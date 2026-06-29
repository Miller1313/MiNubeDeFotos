import os
import sqlite3
import json
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from telegram import Bot
import face_recognition

# ==========================================
# CONFIGURACIÓN (Tus datos de Telegram)
# ==========================================
BOT_TOKEN = "8800785619:AAFWhyFwnXTJl_b_odPIQnd8MHWbt8URtTM"
CHAT_ID = "-1004321494708" 

app = FastAPI()
bot = Bot(token=BOT_TOKEN)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Render nos da una base de datos persistente. Si no la detecta, usa una local para pruebas.
DATABASE_URL = os.getenv("DATABASE_URL", "photos_data.db")

def init_db():
    # Conector inteligente que se adapta si es SQLite (local) o PostgreSQL (Render)
    if DATABASE_URL.startswith("postgres"):
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        conn = sqlite3.connect(DATABASE_FILE)
        
    cursor = conn.cursor()
    
    # Sintaxis compatible para ambas BD
    if DATABASE_URL.startswith("postgres"):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id SERIAL PRIMARY KEY,
                file_id TEXT UNIQUE,
                caption TEXT,
                faces TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS known_faces (
                name TEXT PRIMARY KEY,
                encoding TEXT,
                avatar_file_id TEXT
            )
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT UNIQUE,
                caption TEXT,
                faces TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS known_faces (
                name TEXT PRIMARY KEY,
                encoding TEXT,
                avatar_file_id TEXT
            )
        ''')
    conn.commit()
    conn.close()

try:
    init_db()
except Exception as e:
    print(f"Error iniciando BD: {e}")

class PhotoRegister(BaseModel):
    file_id: str
    caption: str = ""

class FaceRegister(BaseModel):
    name: str
    file_id: str

async def process_faces_in_photo(file_id: str):
    try:
        file = await bot.get_file(file_id)
        temp_path = f"temp_{file_id}.jpg"
        await file.download_to_drive(temp_path)

        image = face_recognition.load_image_file(temp_path)
        face_encodings = face_recognition.face_encodings(image)
        detected_names = []

        if len(face_encodings) > 0:
            if DATABASE_URL.startswith("postgres"):
                import psycopg2
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            else:
                conn = sqlite3.connect(DATABASE_URL)
            cursor = conn.cursor()
            cursor.execute("SELECT name, encoding FROM known_faces")
            rows = cursor.fetchall()
            conn.close()

            known_encodings = [json.loads(r[1]) for r in rows]
            known_names = [r[0] for r in rows]

            for encoding in face_encodings:
                name = "Desconocido"
                if known_encodings:
                    matches = face_recognition.compare_faces(known_encodings, encoding, tolerance=0.6)
                    if True in matches:
                        first_match_index = matches.index(True)
                        name = known_names[first_match_index]
                detected_names.append(name)

        if os.path.exists(temp_path):
            os.remove(temp_path)

        return detected_names
    except Exception as e:
        print(f"Error en IA: {e}")
        return []

@app.get("/photos")
def get_photos():
    if DATABASE_URL.startswith("postgres"):
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT file_id, caption, faces FROM photos ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [{"file_id": r[0], "caption": r[1], "faces": json.loads(r[2]) if r[2] else []} for r in rows]

@app.get("/faces")
def get_faces():
    if DATABASE_URL.startswith("postgres"):
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    cursor.execute("SELECT name, avatar_file_id FROM known_faces")
    rows = cursor.fetchall()
    conn.close()
    return [{"name": r[0], "avatar_file_id": r[1]} for r in rows]

@app.post("/register-photo")
async def register_photo(data: PhotoRegister):
    if DATABASE_URL.startswith("postgres"):
        import psycopg2
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    else:
        conn = sqlite3.connect(DATABASE_URL)
    cursor = conn.cursor()
    detected_faces = await process_faces_in_photo(data.file_id)
    faces_json = json.dumps(detected_faces)
    try:
        if DATABASE_URL.startswith("postgres"):
            cursor.execute("INSERT INTO photos (file_id, caption, faces) VALUES (%s, %s, %s) ON CONFLICT (file_id) DO UPDATE SET caption = EXCLUDED.caption, faces = EXCLUDED.faces", (data.file_id, data.caption, faces_json))
        else:
            cursor.execute("INSERT OR REPLACE INTO photos (file_id, caption, faces) VALUES (?, ?, ?)", (data.file_id, data.caption, faces_json))
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))
    conn.close()
    return {"status": "success", "detected_faces": detected_faces}

@app.post("/register-face")
async def register_face(data: FaceRegister):
    try:
        file = await bot.get_file(data.file_id)
        temp_path = f"temp_reg_{data.file_id}.jpg"
        await file.download_to_drive(temp_path)

        image = face_recognition.load_image_file(temp_path)
        encodings = face_recognition.face_encodings(image)

        if not encodings:
            os.remove(temp_path)
            raise HTTPException(status_code=400, detail="No se detectó rostro")

        encoding_json = json.dumps(encodings[0].tolist())
        if DATABASE_URL.startswith("postgres"):
            import psycopg2
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        else:
            conn = sqlite3.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        if DATABASE_URL.startswith("postgres"):
            cursor.execute("INSERT INTO known_faces (name, encoding, avatar_file_id) VALUES (%s, %s, %s) ON CONFLICT (name) DO UPDATE SET encoding = EXCLUDED.encoding, avatar_file_id = EXCLUDED.avatar_file_id", (data.name, encoding_json, data.file_id))
        else:
            cursor.execute("INSERT OR REPLACE INTO known_faces (name, encoding, avatar_file_id) VALUES (?, ?, ?)", (data.name, encoding_json, data.file_id))
            
        conn.commit()
        conn.close()

        if os.path.exists(temp_path):
            os.remove(temp_path)
        return {"status": "success", "message": f"{data.name} registrado"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)