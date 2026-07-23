# macOS uygulaması

scripts/install-macos.sh yerel backend release’ini oluşturur, Claude Window Starter.app paketini /Applications içine kurar ve launchd agent’larını yükler. Uygulama macOS 13+ hedefler ve Apple Silicon ile Intel x86_64 yollarını destekler.

Menü uygulaması yalnız yerel JSON CLI’ı çağırır. Claude, Telegram, Bakım ve Kayıtlar sekmeleri aynı backend sözleşmesini kullanır.

Arka plan segmenti açıkken helper:

- internet yolunu NWPathMonitor ile izler,
- boşta uyku için process-scoped IOPMAssertion tutar,
- planlanan zamanı ve bekleyen ağı Python backend’e bildirir,
- ekranın kararmasına izin verir.

Kapak kapatma zorunlu uyku olduğundan, accessoriesiz kapalı-kapak çalışma garanti edilmez. Sistem uyursa pending_automatic diske yazılır ve uyanışta bağlantı geldiğinde tek deneme yapılır.

Build:

    scripts/build-macos-app.sh
    codesign --verify --deep --strict "dist/Claude Window Starter.app"

Paket ad-hoc imzalıdır; App Store signing/notarization kapsam dışıdır.
