from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import psycopg2
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv() 

# 1. Veritabanı Bağlantı Ayarları
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "koski_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

# 2. Veritabanı ve Tabloları Kuran "İşçi" Fonksiyonu
def veritabani_kur():
    try:
        # Veritabanının kapısını çalıyoruz
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 1. Tablo: Sohbet Oturumları (Zaten varsa dokunmaz)
        cursor.execute('''CREATE TABLE IF NOT EXISTS SohbetOturumlari 
                          (session_id TEXT PRIMARY KEY, 
                       kullanici_tipi TEXT,
                       olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 2. Tablo: Mesajlar
        cursor.execute('''CREATE TABLE IF NOT EXISTS Mesajlar 
                          (id SERIAL PRIMARY KEY, 
                           session_id TEXT REFERENCES SohbetOturumlari(session_id), 
                           gonderen TEXT, 
                           mesaj TEXT,
                          zaman TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        #3. Tablo: Personel Hesapları
        cursor.execute('''CREATE TABLE IF NOT EXISTS Personeller 
                          (id SERIAL PRIMARY KEY, 
                           kullanici_adi TEXT UNIQUE, 
                           sifre TEXT)''')
        # Test için varsayılan bir personel ekleyelim (Eğer yoksa)
        varsayilan_kullanici = os.getenv("PERSONEL_KULLANICI_ADI", "personel")
        varsayilan_sifre = os.getenv("PERSONEL_SIFRE", "123456")

        cursor.execute(
            '''INSERT INTO Personeller (kullanici_adi, sifre) 
                VALUES (%s, %s) 
                ON CONFLICT (kullanici_adi) 
                Do UPDATE SET sifre = EXCLUDED.sifre''',
            (varsayilan_kullanici, varsayilan_sifre)
        )
        conn.commit() # Değişiklikleri onayla
        cursor.close()
        conn.close()  # Kapıyı kapat
        print("Harika! Veritabanı bağlantısı başarılı, vatandaş ve personel tabloları hazır.")
    except Exception as e:
        print("Eyvah! Veritabanına bağlanırken bir sorun çıktı:", e)

# Uygulama başlarken bu işçiyi bir kere çalıştır
veritabani_kur()

def mesaji_kaydet(session_id, gonderen, mesaj):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    #oturum yoksa oluştur
    cursor.execute("INSERT INTO SohbetOturumlari (session_id, kullanici_tipi) VALUES (%s, %s) ON CONFLICT (session_id) DO NOTHING", (session_id, 'Vatandaş'))
    #mesajı ekle
    cursor.execute("INSERT INTO Mesajlar (session_id, gonderen, mesaj) VALUES (%s, %s, %s)", (session_id, gonderen, mesaj))
    conn.commit()
    cursor.close()
    conn.close()



# 1. Kuryemizi oluşturuyoruz
app = FastAPI()

# GÜVENLİK KAPISI (CORS): Vitrinden (HTML) gelen paketlerin reddedilmesini önler
# Bu ayar, tarayıcının "Bu site yabancı bir kaynaktan veri alıyor, engelleyeyim" 
# demesini durdurur ve KOSKİ arayüzümüzün Kurye ile konuşmasına izin verir.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500",
    "http://localhost:5500"], # Tüm kaynaklardan gelen isteklere izin ver (Geliştirme aşaması için)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Vitrinden gelecek paketin şekli
class GelenMesaj(BaseModel):
    session_id: str
    vatandasAd: str
    mesaj: str

class PersonelGiris(BaseModel):
    kullanici_adi: str
    sifre: str   

#VATANDAŞ PANELİ
# 3. Kuryenin beklediği kapı (Endpoint)
@app.post("/api/talepler/yeni") 
def talep_kaydet(talep: GelenMesaj):
    print("İstek backende ulaştı!")
    mesaji_kaydet(talep.session_id, 'Vatandaş', talep.mesaj)  # Mesajı veritabanına kaydet

    # 4. Beyin'e (Qwen'e) vereceğimiz talimat
    prompt = (
        "Sen Konya KOSKİ'nin resmi sanal asistanısın. "
        "Her zaman ve sadece türkçe konuş."
        "Kullanıcı sana ilk mesajı attığında, ona KVKK aydınlatma metnini onaylayıp onaylamadığını sor. Kullanıcı açıkça 'Onaylıyorum' diyene kadar hiçbir KOSKİ sorusuna cevap verme. Eğer 'Onaylamıyorum' derse sohbeti Türkçe bir veda mesajıyla sonlandır."
        "Görevin SADECE su arızaları, fatura ödemeleri, su kesintileri ve KOSKİ hizmetleri hakkında bilgi vermektir. "
        "KURAL 1: Eğer kullanıcı sana su, fatura ve KOSKİ hizmetleri gibi konu  DIŞINDA bir soru sorarsa KESİNLİKLE cevap verme! "
        "KURAL 2: İlgisiz sorularda sadece kibarca 'Ben KOSKİ asistanıyım, size sadece KOSKİ hizmetleri ve su konularında yardımcı olabilirim.' de ve konuyu kapat. "
        f"Vatandaşın Mesajı: {talep.mesaj}"
    )

    # 5. Beyin'i aramak için numara
    ollama_url = "http://localhost:11434/api/generate"
    ollama_istek = {
        "model": "qwen2.5",
        "prompt": prompt,
        "stream": False 
    }

    try:
        # 120 saniye içinde cevap gelmezse patlasın, hatayı görelim
        cevap = requests.post(ollama_url, json=ollama_istek, timeout=120) 
        uretilen_cevap = cevap.json().get("response")
    except requests.exceptions.Timeout:
        uretilen_cevap = "Üzgünüm, yapay zeka cevap vermekte çok gecikti."
    except Exception as e:
        uretilen_cevap = f"Bir hata oluştu: {str(e)}"

    mesaji_kaydet(talep.session_id, 'Bot', uretilen_cevap)  # Bot cevabını veritabanına kaydet
    # 6. Vitrine dönüş
    return {
        "session_id": talep.session_id,
        "yapayZekaCevabi": uretilen_cevap}

#PERSONEL PANELİ
# Personel Paneli 1: Tüm aktif oturumları listele
@app.get("/api/personel/oturumlar")
def aktif_oturumlari_getir():
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    # En son mesaj atılan oturumları en üste getirir
    cursor.execute("SELECT session_id, olusturma_tarihi FROM SohbetOturumlari ORDER BY olusturma_tarihi DESC")
    oturumlar = cursor.fetchall()
    cursor.close()
    conn.close()
    
    liste = []
    for oturum in oturumlar:
        liste.append({"session_id": oturum[0], "tarih": str(oturum[1])})
    return {"oturumlar": liste}

# Personel Paneli 2: Seçilen oturumun mesajlarını getir
@app.get("/api/personel/mesajlar/{session_id}")
def oturum_mesajlarini_getir(session_id: str):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT gonderen, mesaj, zaman FROM Mesajlar WHERE session_id = %s ORDER BY id ASC", (session_id,))
    mesajlar = cursor.fetchall()
    cursor.close()
    conn.close()
    
    liste = []
    for m in mesajlar:
        liste.append({"gonderen": m[0], "mesaj": m[1], "zaman": str(m[2])})
    return {"mesajlar": liste}
@app.post("/api/personel/giris")
def personel_giris_kontrol(bilgiler: PersonelGiris):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Personeller WHERE kullanici_adi = %s AND sifre = %s", (bilgiler.kullanici_adi, bilgiler.sifre))
    personel = cursor.fetchone()
    cursor.close()
    conn.close()

    if personel:
        return {"durum": True, "mesaj": "Giriş başarılı!"}
    else:
        return {"durum": False, "mesaj": "Kullanıcı adı veya şifre yanlış."}