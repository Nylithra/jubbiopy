# 🎫 Gelişmiş Ticket + Hoş Geldin Botu

JubbioPy ile yazılmış, kullanıma hazır ticket ve giriş/çıkış botu.

## Çalıştırma (Windows)

```bat
cd D:\ali\jubbiopy-claude-pensive-goldberg-sj8883
python -m pip install -e .
set BOT_TOKEN=tokenin
python examples\ticket_bot\bot.py
```

Ayarlar `examples\ticket_bot\ticket_data.json` dosyasına kaydedilir (başka yer için `set TICKET_DATA=yol\dosya.json`).

## Kurulum (sunucuda, "Sunucuyu Yönet" izni gerekir)

1. `/ayarla ticket yetkili_rol:@Destek kategori:#Ticketlar log_kanal:#ticket-log limit:1`
2. `/ticket-panel kanal:#destek` → paneli gönderir
3. `/ayarla hosgeldin kanal:#hos-geldin mesaj:Hoş geldin {kullanici}!` (isteğe bağlı)
4. `/ayarla ayrilma kanal:#gidenler` (isteğe bağlı)
5. `/ayarla otorol rol:@Üye` (isteğe bağlı)
6. `/ayarla goster` → tüm ayarlar ve istatistikler

Mesaj değişkenleri: `{kullanici}` (etiket), `{isim}`, `{sunucu}`, `{uye_sayisi}`.
Bir sistemi kapatmak için: `/ayarla kapat sistem:Hoş geldin`.

## Ticket kullanımı

| Nerede | Ne yapar |
|---|---|
| Paneldeki menü | Kategori seç → form (konu + açıklama) → özel kanal açılır |
| **Ticket Aç** butonu | Genel destek ticket'ı açar |
| **🙋 Sahiplen** butonu / `/ticket sahiplen` | Yetkili ticket'ı üstlenir |
| **🔒 Kapat** butonu / `/ticket kapat sebep:...` | Onay sonrası döküm alınır, kanal silinir |
| `/ticket ekle kullanici:@biri` | Kişiyi ticket'a ekler |
| `/ticket cikar kullanici:@biri` | Kişiyi ticket'tan çıkarır |
| `/ticket bilgi` | Ticket bilgilerini gösterir |

Kapatılan her ticket'ın mesaj dökümü (`ticket-0001.txt`) log kanalına ve ticket sahibine DM olarak gönderilir.

Ticket kanalını sadece ticket sahibi, yetkili rolü, eklenen kişiler ve bot görebilir.
Yöneticiler ve sunucu sahibi her zaman yetkilidir.

## Özelleştirme

`bot.py` başındaki `CATEGORIES` listesini düzenleyerek kategorileri, `DEFAULT_WELCOME` /
`DEFAULT_LEAVE` ile varsayılan mesajları değiştirebilirsin.
