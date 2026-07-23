# Sorun giderme

- API_KEY_DETECTED: yasaklı API/provider değişkenlerini kaldırın; abonelik oturumu dışında bir credential eklemeyin.
- CLAUDE_NOT_AUTHENTICATED: Mac’te Claude Code oturumunu yenileyin, önce dry-run sonra gerçek smoke çağrısı yapın.
- NETWORK_UNAVAILABLE veya pending_connectivity: bağlantı geri geldiğinde helper otomatik olarak tek deneme yapar.
- ALREADY_RAN_TODAY: günlük duplicate koruması çalıştı; manuel çalışma yine yapılabilir.
- MODEL_UNAVAILABLE: auto, başarılı çağrıdan önce Haiku alias’ını sınar ve gerektiğinde hesap varsayılanına döner.
- LAUNCHD_FAILED: uygulamayı yeniden kurun; plist dosyalarının plutil -lint sonucunu kontrol edin.
- NO_HEALTHY_PREVIOUS_RELEASE: geri dönülecek sağlıklı yerel release yoktur.
- Kapak kapatılınca işlem durmuşsa bu macOS zorunlu uyku davranışıdır; cihaz uyandığında bekleyen iş yeniden değerlendirilir.

Tanı için uygulamadaki Durum, Teşhis, Sağlık kontrolü ve Kayıtlar düğmelerini kullanın. Sır, tam stderr, ham environment veya Telegram update payload’ı paylaşmayın.
