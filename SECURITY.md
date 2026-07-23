# Güvenlik modeli

## Sırlar

Telegram tokenı SecureField/stdin üzerinden macOS Keychain’e yazılır. Token config, state, argv, environment, log veya release içine yazılmaz. Keychain’den okuyan launchd helper tokenı anonim stdin üzerinden bot process’ine aktarır.

Claude çalışması shell=False, prompt stdin, allowlist environment, boş araç seti, session persistence kapalı, capability-gated bayraklar ve timeout ile yürütülür. Yasaklı API/provider değişkenleri algılanırsa gerçek çağrı durur.

## Arka plan

Uygulama yalnız process-scoped IOPMAssertion kullanır; pmset, sudo veya sistem genelindeki güç ayarlarını değiştirmez. Assertion ekran uykusunu engellemez. Kapak kapatma gibi zorunlu uyku durumlarında macOS çalışmayı durdurabilir; uyanma sonrası durum ve ağ yeniden değerlendirilir.

## Telegram

Komutlar sayısal kullanıcı/sohbet allowlist’i, private-chat varsayılanı, cooldown, escaping ve kullanıcıya bağlı kısa ömürlü confirmation nonce’larıyla korunur. Polling offset’i atomik kaydedilir; bot lock çift instance’ı engeller. Ham Telegram update, tam stderr ve environment loglanmaz.

## Release

Release’ler Mac’te immutable dizinlerde tutulur. Config, state, log ve Keychain dışı sırlar release’lerden bağımsızdır. current ve previous geçici symlink + atomik rename ile değiştirilir; post-health başarısızlığında eski release geri alınır. Beş release tutulurken aktif ve fallback release’ler korunur.

## Olay müdahalesi

Bir sır açığa çıkarsa önce tokenı iptal edin ve yenisini üretin. Loglarda yalnız sanitize edilmiş JSONL alanları bulunur. Sırları sohbet, issue veya Git geçmişine yapıştırmayın.
