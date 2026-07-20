from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import requests
import psycopg2
from datetime import datetime
import os
from dotenv import load_dotenv
import re
load_dotenv() 



# 1. Veritabanı Bağlantı Ayarları
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "koski_db"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

# 2. Veritabanı ve Tabloları Kuran "İşçi" Fonksiyonu (GÜNCELLENDİ)
def veritabani_kur():
    try:
        # Veritabanının kapısını çalıyoruz
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        # 1. BİRİMLER TABLOSU (En Bağımsız Tablo - Önce bu kurulmalı)
        cursor.execute('''CREATE TABLE IF NOT EXISTS Birimler 
                          (birim_id SERIAL PRIMARY KEY, 
                           birim_adi VARCHAR(100) NOT NULL UNIQUE)''')

        # 2. PERSONELLER TABLOSU (Birimlere Bağlı)
        cursor.execute('''CREATE TABLE IF NOT EXISTS Personeller 
                          (personel_id SERIAL PRIMARY KEY, 
                           ad_soyad VARCHAR(100), 
                           kullanici_adi VARCHAR(50) UNIQUE NOT NULL, 
                           sifre VARCHAR(100) NOT NULL, 
                           yetki_seviyesi VARCHAR(50) DEFAULT 'Standart', 
                           birim_id INT REFERENCES Birimler(birim_id) ON DELETE SET NULL)''')

        # 3. SOHBET OTURUMLARI TABLOSU (Birimlere Bağlı & KVKK Sütunu Eklendi)
        cursor.execute('''CREATE TABLE IF NOT EXISTS SohbetOturumlari 
                          (session_id TEXT PRIMARY KEY, 
                           kullanici_tipi TEXT DEFAULT 'Vatandaş',
                           olusturma_tarihi TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                           kvkk_onay BOOLEAN DEFAULT FALSE,
                           durum VARCHAR(30) DEFAULT 'Yeni',
                          ilgili_birim_id INT REFERENCES Birimler(birim_id) ON DELETE SET NULL)''')
        
        # 4. MESAJLAR TABLOSU (Sohbet Oturumlarına Bağlı)
        cursor.execute('''CREATE TABLE IF NOT EXISTS Mesajlar 
                          (id SERIAL PRIMARY KEY, 
                           session_id TEXT REFERENCES SohbetOturumlari(session_id) ON DELETE CASCADE, 
                           gonderen TEXT, 
                           mesaj TEXT, 
                           zaman TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # 5. VARSAYILAN VERİLERİN EKLENMESİ (Seed Data)
        # Birimler (Departmanlar) ekleniyor. 'ON CONFLICT (birim_id) DO NOTHING' ile daha önce eklenmişse hata vermesi engelleniyor.
        birimler = [
            (1, "Abonelik İşlemleri"),
            (2, "Sayaç İşlemleri"),
            (3, "Fatura ve Ödeme İşlemleri"),
            (4, "Su Kayıpları Kontrolü"),
            (5, "Su Şebeke Bakım Onarım"),
            (6, "Su Temin ve Kaynak Geliştirme"),
            (7, "Plan Proje"),
            (8, "Müşteri Hizmetleri")
        ]

        for b_id, b_adi in birimler:
            cursor.execute("""
                INSERT INTO Birimler (birim_id, birim_adi)
                VALUES (%s, %s)
                ON CONFLICT (birim_id)
                DO UPDATE SET birim_adi = EXCLUDED.birim_adi
            """, (b_id, b_adi))
            
        # Yönetici personel ekleniyor. Şifre ve Ad bilgisi .env dosyasından çekiliyor.
        p_ad = os.getenv("PERSONEL_KULLANICI_ADI", "Admin")
        p_sifre = os.getenv("PERSONEL_SIFRE", "admin123")
        cursor.execute("""
            INSERT INTO Personeller (ad_soyad, kullanici_adi, sifre, yetki_seviyesi, birim_id) 
            VALUES (%s, %s, %s, 'Yönetici', 8) 
            ON CONFLICT (kullanici_adi) DO NOTHING
        """, (p_ad, p_ad, p_sifre))

        # Değişiklikleri onayla ve kapıyı kapat
        conn.commit()
        cursor.close()
        conn.close()
        print("Harika! Veritabanı bağlantısı başarılı, yeni İLİŞKİSEL tablolar hazır.")
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
    kvkk_onay: Optional[bool] = False  # KVKK onayı varsayılan olarak False, gönderilmese bile sistem çökmez

class PersonelGiris(BaseModel):
    kullanici_adi: str
    sifre: str   

class DurumGuncelle(BaseModel):
    durum: str    

# VATANDAŞ PANELİ: Yeni Mesaj ve Yapay Zeka Yönlendirmesi
@app.post("/api/talepler/yeni") 
def talep_kaydet(talep: GelenMesaj):
    print(f"[{talep.session_id}] İstek backende ulaştı! KVKK Onayı: {talep.kvkk_onay}")
    
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    
    # 1. OTURUMU VE VATANDAŞ MESAJINI KAYDET
    # Oturum yoksa oluştur, KVKK durumunu güncelle
    cursor.execute("""
        INSERT INTO SohbetOturumlari (session_id, kullanici_tipi, kvkk_onay) 
        VALUES (%s, 'Vatandaş', %s) 
        ON CONFLICT (session_id) DO UPDATE SET kvkk_onay = EXCLUDED.kvkk_onay
    """, (talep.session_id, talep.kvkk_onay))
    
    # Vatandaşın mesajını ekle
    cursor.execute("INSERT INTO Mesajlar (session_id, gonderen, mesaj) VALUES (%s, %s, %s)", 
                   (talep.session_id, 'Vatandaş', talep.mesaj))
    conn.commit()

    # 2. BEYİN'E (QWEN'E) VERİLEN AKILLI TALİMAT (PROMPT)
    prompt = (
    "Sen Konya KOSKİ'nin resmi dijital asistanısın. HER ZAMAN SADECE TÜRKÇE KONUŞ.\n"
    "Cevapların kısa, anlaşılır, resmi ve kurumsal olmalıdır.\n"
    "Görevin vatandaşın mesajını anlamak, uygun bir cevap vermek ve mesajı doğru KOSKİ birimine yönlendirmektir.\n\n"

    "BİRİM YÖNLENDİRME KURALLARI:\n"
    "1. Abonelik açma, abonelik iptali, isim değişikliği, abonelik devri ve yeni abonelik başvuruları için cevabın sonuna kesinlikle [BIRIM:1] yaz.\n"
    "2. Sayaç arızası, sayaç değişimi, sayaç kontrolü, endeks okuma ve sayaçla ilgili teknik konular için cevabın sonuna kesinlikle [BIRIM:2] yaz.\n"
    "3. Fatura sorgulama, borç sorgulama, ödeme, yüksek fatura, ödeme görünmeme ve fatura itirazı konuları için cevabın sonuna kesinlikle [BIRIM:3] yaz.\n"
    "4. Kaçak su ihbarı, usulsüz kullanım, sayaçsız bağlantı ve su kaybı bildirimleri için cevabın sonuna kesinlikle [BIRIM:4] yaz.\n"
    "5. Su kesintisi, boru patlağı, şebeke arızası, düşük su basıncı ve yolda su akması gibi teknik arızalar için cevabın sonuna kesinlikle [BIRIM:5] yaz.\n"
    "6. Su kaynakları, baraj, kuyu, su temini ve kaynak geliştirme ile ilgili genel talepler için cevabın sonuna kesinlikle [BIRIM:6] yaz.\n"
    "7. Yeni altyapı projeleri, yeni hat çalışmaları, planlanan kazı çalışmaları ve proje süreçleri için cevabın sonuna kesinlikle [BIRIM:7] yaz.\n"
    "8. Genel bilgi, iletişim, çalışma saatleri, yönlendirme ve sınıflandırılamayan KOSKİ talepleri için cevabın sonuna kesinlikle [BIRIM:8] yaz.\n\n"

    "KOSKİ, su, kanalizasyon, abonelik, sayaç, fatura, arıza, altyapı ve kurum hizmetleri dışındaki konulara cevap verme.\n"
    "Konu KOSKİ dışındaysa sadece şu cümleyi yaz: "
    "'Ben KOSKİ dijital asistanıyım, yalnızca kurumumuzla ilgili konularda yardımcı olabilirim.' "
    "ve sonuna kesinlikle [BIRIM:8] ekle.\n\n"

    "ÖNEMLİ: Her cevabın sonunda mutlaka yalnızca bir tane [BIRIM:x] etiketi bulunmalıdır."
)

    # 3. BEYİN'E İSTEK AT
    ollama_url = "http://localhost:11434/api/chat"
    ollama_istek = {
        "model": "qwen2.5", 
        "messages": [
            {"role": "system", "content": prompt},  # Yapay zekanın anayasası
            {"role": "user", "content": talep.mesaj}       # Vatandaşın mesajı
        ],
        "stream": False
    }
    try:
        cevap = requests.post(ollama_url, json=ollama_istek, timeout=120) 
        # Chat API'nin cevap yapısı farklıdır, veriyi message -> content içinden çekeriz
        uretilen_cevap = cevap.json().get("message", {}).get("content", "")
    except Exception as e:
        uretilen_cevap = f"Bir hata oluştu: {str(e)} [BIRIM:8]"

    # 4. GİZLİ BİRİM KODUNU AYIKLA VE VERİTABANINI GÜNCELLE
    # Varsayılan birim: 8 - Müşteri Hizmetleri
    birim_id = 8

    # Yapay zekânın cevabında [BIRIM:1] - [BIRIM:8] arası bir etiket aranır.
    birim_eslesme = re.search(r'\[(?:BIRIM|FATURA):(\d+)\]', uretilen_cevap)

    if birim_eslesme:
        gelen_birim_id = int(birim_eslesme.group(1))

        if gelen_birim_id in [1, 2, 3, 4, 5, 6, 7, 8]:
            birim_id = gelen_birim_id

    # Vatandaşa görünmemesi için yalnızca [BIRIM:x] etiketi temizlenir.
    uretilen_cevap = re.sub(r'\[(?:BIRIM|FATURA):\d+\]', '', uretilen_cevap).strip()
    
    # Sohbetin ait olduğu birimi veritabanında güncelle!
    cursor.execute("UPDATE SohbetOturumlari SET ilgili_birim_id = %s WHERE session_id = %s", 
                   (birim_id, talep.session_id))
    conn.commit()

    # 5. BOTUN TEMİZLENMİŞ CEVABINI KAYDET VE VİTRİNE GÖNDER
    cursor.execute("INSERT INTO Mesajlar (session_id, gonderen, mesaj) VALUES (%s, %s, %s)", 
                   (talep.session_id, 'Bot', uretilen_cevap))
    conn.commit()
    
    cursor.close()
    conn.close()

    return {
        "session_id": talep.session_id,
        "yapayZekaCevabi": uretilen_cevap
    }

#PERSONEL PANELİ
# PERSONEL PANELİ 1: Aktif oturumları listele (GÜNCELLENDİ - KVKK ve Birim Filtreli)
@app.get("/api/personel/oturumlar")
def aktif_oturumlari_getir(
    birim_id: Optional[str] = None, 
    yetki_seviyesi: str = "Standart",
    filtre_birim_id: Optional[str] = None
):
    
    print(f"--- Frontend'den gelen Birim ID: {birim_id} | Yetki: {yetki_seviyesi} | Filtre: {filtre_birim_id} ---")

    if birim_id in ["null", "undefined", ""]:
        birim_id = None

    if filtre_birim_id in ["null", "undefined", "", "tum"]:
        filtre_birim_id = None

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    if yetki_seviyesi == "Yönetici":

        if filtre_birim_id:
            cursor.execute("""
                SELECT 
                    s.session_id,
                    s.olusturma_tarihi,
                    s.ilgili_birim_id,
                    COALESCE(b.birim_adi, 'Birim Atanmadı') AS birim_adi,
                    COALESCE(s.durum, 'Yeni') AS durum
                FROM SohbetOturumlari s
                LEFT JOIN Birimler b 
                    ON s.ilgili_birim_id = b.birim_id
                WHERE s.kvkk_onay = TRUE
                  AND s.ilgili_birim_id = %s
                ORDER BY s.olusturma_tarihi DESC
            """, (filtre_birim_id,))
        else:
            cursor.execute("""
                SELECT 
                    s.session_id,
                    s.olusturma_tarihi,
                    s.ilgili_birim_id,
                    COALESCE(b.birim_adi, 'Birim Atanmadı') AS birim_adi,
                    COALESCE(s.durum, 'Yeni') AS durum
                FROM SohbetOturumlari s
                LEFT JOIN Birimler b 
                    ON s.ilgili_birim_id = b.birim_id
                WHERE s.kvkk_onay = TRUE
                ORDER BY s.olusturma_tarihi DESC
            """)

    else:
        cursor.execute("""
            SELECT 
                s.session_id,
                s.olusturma_tarihi,
                s.ilgili_birim_id,
                COALESCE(b.birim_adi, 'Birim Atanmadı') AS birim_adi,
                COALESCE(s.durum, 'Yeni') AS durum
            FROM SohbetOturumlari s
            LEFT JOIN Birimler b 
                ON s.ilgili_birim_id = b.birim_id
            WHERE s.kvkk_onay = TRUE
              AND s.ilgili_birim_id = %s
            ORDER BY s.olusturma_tarihi DESC
        """, (birim_id,))

    oturumlar = cursor.fetchall()

    cursor.close()
    conn.close()

    return {
        "oturumlar": [
            {
                "session_id": o[0],
                "tarih": str(o[1]),
                "birim_id": o[2],
                "birim_adi": o[3],
                "durum": o[4]
            }
            for o in oturumlar
        ]
    }

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
# PERSONEL PANELİ 3: Akıllı Giriş Kontrolü
@app.post("/api/personel/giris")
def personel_giris_kontrol(bilgiler: PersonelGiris):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    # Şifre ve kullanıcı adını kontrol ediyoruz
    cursor.execute("SELECT * FROM Personeller WHERE kullanici_adi = %s AND sifre = %s", (bilgiler.kullanici_adi, bilgiler.sifre))
    personel = cursor.fetchone()
    cursor.close()
    conn.close()

    if personel:
        # Veritabanından gelen satır (tuple) yapısı:
        # 0: personel_id, 1: ad_soyad, 2: kullanici_adi, 3: sifre, 4: yetki_seviyesi, 5: birim_id
        
        return {
            "durum": True, 
            "mesaj": "Giriş başarılı!",
            "ad_soyad": personel[1],
            "yetki_seviyesi": personel[4],
            "birim_id": personel[5]
        }
    else:
        return {"durum": False, "mesaj": "Kullanıcı adı veya şifre yanlış."}
    
# PERSONEL PANELİ 4: Görüşme durumunu güncelle
@app.put("/api/personel/oturumlar/{session_id}/durum")
def oturum_durumunu_guncelle(session_id: str, veri: DurumGuncelle):
    izinli_durumlar = ["Yeni", "İnceleniyor", "Tamamlandı"]

    if veri.durum not in izinli_durumlar:
        return {
            "durum": False,
            "mesaj": "Geçersiz durum bilgisi."
        }

    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE SohbetOturumlari
        SET durum = %s
        WHERE session_id = %s
    """, (veri.durum, session_id))

    conn.commit()

    guncellenen_kayit_sayisi = cursor.rowcount

    cursor.close()
    conn.close()

    if guncellenen_kayit_sayisi == 0:
        return {
            "durum": False,
            "mesaj": "Güncellenecek sohbet oturumu bulunamadı."
        }

    return {
        "durum": True,
        "mesaj": "Görüşme durumu başarıyla güncellendi.",
        "yeni_durum": veri.durum
    } 