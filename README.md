# Claude Window Starter

Claude Window Starter, Mac üzerinde günlük tek bir gerçek Claude Code abonelik isteğini güvenli biçimde başlatır. Uygulama macOS 13+ için hazırlanmıştır.

Başarılı bir Claude yanıtı, beş saatlik kullanım penceresinin başladığını teknik olarak kanıtlamaz. Otomasyon, Telegram ve arka planda çalışma varsayılan olarak kapalıdır.

## Güvenli varsayılanlar

- Saat: 08:00 Europe/Istanbul
- Prompt: Respond with OK.
- Model: auto
- Timeout: 120 saniye
- Beş yerel release tutulur.
- Runtime Python yalnızca standart kütüphaneye dayanır.
- Config, state, loglar ve Keychain sırları Git dışında kalır.

## Kurulum

    scripts/build-local.sh
    scripts/install-macos.sh
    open "/Applications/Claude Window Starter.app"

Kurulum backend’i ~/Library/Application Support/ClaudeWindowStarter altına yerleştirir, uygulamayı /Applications içine koyar ve launchd yardımcılarını yükler. Ayarlar kalıcıdır; Telegram tokenı yalnız Keychain’de tutulur.

Kaldırma:

    scripts/uninstall-macos.sh

--purge yalnız config/state/logları da silmek istediğinizde kullanılmalıdır. Keychain değerleri kullanıcı onayı olmadan geri gösterilmez.

## Arka planda çalışma

Uygulamadaki “Arka Planda Çalışma: Kapalı | Açık” segmenti:

- Açık: ekran kararabilir, boşta sistem uykusu uygulama assertion’ı ile önlenir; internet geçişleri izlenir.
- Kapalı: sürekli uyku assertion’ı tutulmaz.

Kapak kapatma macOS’ta zorunlu uyku olduğundan, aksesuar olmayan kapalı-kapak durumunda sürekli çalışma garanti edilemez. Sistem uyursa sayaç mutlak zamana göre korunur; uyanıp internet geldiğinde bekleyen çalışma tek kez denenir.

## Telegram

BotFather’dan botu oluşturup tokenı uygulamadaki SecureField ile Keychain’e kaydedin. Kullanıcı ve özel sohbet ID’lerini sayısal allowlist alanlarına girin, ayarları kaydedin ve Telegram bağlantısını test edin. Kanal yalnız bildirim hedefidir; komutlar private-chat allowlist’ine bağlıdır.

Komutlar: /status, /health, /diagnose, /run, /dryrun, /schedule, /settime, /timezone, /settimezone, /enable, /disable, /background, /next, /last, /logs, /model, /setmodel, /prompt, /setprompt, /timer, /version.

Run ve prompt değişikliği kullanıcıya ve sohbete bağlı, kısa ömürlü confirmation nonce’ı ister. Polling offset’i atomik kaydedilir ve tek bot kilidiyle çift instance engellenir.

## CLI

    status | diagnose | health | run | config | schedule
    telegram-bot | telegram-test | logs | service
    releases | rollback | version

--json sürümlemeli sonuç zarfı üretir. Gerçek Claude ve Telegram testleri kullanıcı açıkça etkinleştirmeden çalıştırılmaz.

## Yerel release ve rollback

Her kurulum kendi immutable release dizinine, manifestine, current/previous symlink’lerine ve sağlık sonucuna sahiptir. Sağlıksız release etkinleştirilmez; rollback yalnız sağlıklı yerel release’e yapılır. Varsayılan retention beştir.

Detaylar için docs/MACOS.md, docs/TELEGRAM.md, docs/LOCAL_RELEASES.md, docs/TROUBLESHOOTING.md ve SECURITY.md belgelerine bakın.
