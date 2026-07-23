# Yerel release ve rollback

Kurulum her backend kopyasını ~/Library/Application Support/ClaudeWindowStarter/releases altında immutable release olarak saklar. current çalışan, previous son fallback symlink’idir.

Yeni release için kaynak temiz olmalı, Python syntax/import/test kontrolleri ve uygulama build’i geçmelidir. Symlink geçişi atomiktir. Sağlık kontrolü başarısızsa eski release geri alınır.

    claude-window-starter --json releases
    claude-window-starter --json rollback --yes

Retention beş release’tir; current ve previous release silinmez. Config, state, log ve Keychain release değişimlerinde korunur.
