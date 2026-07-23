# Telegram kurulumu

1. BotFather ile bot oluşturun.
2. Tokenı uygulamadaki SecureField’e yapıştırın ve Tokenı Keychain’e kaydet düğmesine basın.
3. Sayısal Telegram kullanıcı ID’nizi ve private chat ID’nizi allowlist alanlarına girin.
4. Gerekirse bildirim chat/kanal ID’sini ekleyin.
5. Telegram’ı etkinleştirip ayarları kaydedin.
6. Telegram bağlantısını test et düğmesine basın.

Bot long polling kullanır ve inbound port açmaz. Kanal yalnızca bildirim hedefidir; komutlar allowlist içindeki private chat’lerden kabul edilir.

Çalıştırma ve prompt değiştirme confirmation nonce ister. Token hiçbir zaman geri gösterilmez veya loglanmaz.
