# 🎵 Gelişmiş Müzik Botu

## Kurulum ve çalıştırma (Windows)

```bat
python -m pip install -e ".[voice]" yt-dlp
set BOT_TOKEN=tokenin
python examples\muzik_bot\bot.py
```

FFmpeg kurmak gerekmez (PyAV kullanılır). Ayarlar `examples\muzik_bot\muzik_data.json` dosyasındadır.

## Komutlar

| Komut | Açıklama |
|---|---|
| `/cal sarki:` | Şarkı adı, YouTube/SoundCloud linki veya **çalma listesi** (en fazla 100 şarkı) |
| `/ara sorgu:` | YouTube'da 5 sonuç gösterir, menüden seçilir |
| `/sira [sayfa]` | Şarkı sırası (toplam süre ile) |
| `/simdi` | Şu an çalan şarkı + ilerleme çubuğu + kontrol butonları |
| `/gec`, `/atla sira:`, `/onceki` | Geç, belirli şarkıya atla, önceki şarkıya dön |
| `/duraklat`, `/devam`, `/durdur` | Duraklat / devam et / durdur ve sırayı temizle |
| `/ses seviye:` | 0–200 arası ses (çalarken anında değişir, sunucu için hatırlanır) |
| `/dongu mod:` | Kapalı / Şarkı / Sıra |
| `/karistir`, `/kaldir sira:`, `/tasi nereden: nereye:`, `/temizle` | Sıra yönetimi |
| `/ayril` | Kanaldan ayrıl |
| `/247` | 24/7 modu (yönetici) — kanaldan hiç ayrılmaz |
| `/dj-rol [rol]` | DJ rolü (yönetici) — kontrol komutlarını sınırlar |

Her şarkıda **Şimdi Çalıyor** paneli gelir: ⏮️ ⏸️ ⏭️ ⏹️ 🔁 / 🔉 🔊 🔀 📜 🔄 butonları.

## Kurallar

- Kontrol için botla **aynı ses kanalında** olmalısın.
- DJ rolü ayarlıysa kontrol komutlarını sadece DJ'ler ve yöneticiler kullanabilir. Şarkıyı isteyen kişi kendi şarkısını geçebilir.
- Sıra bitince veya kanalda kimse kalmayınca bot 3 dakika sonra ayrılır (24/7 kapalıysa). Kanal boşalınca müzik duraklar, biri gelince devam eder.
