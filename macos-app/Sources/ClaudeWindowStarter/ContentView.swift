import SwiftUI

struct ContentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 12) {
            header
            TabView {
                claude.tabItem { Label("Claude", systemImage: "sparkles") }
                telegram.tabItem { Label("Telegram", systemImage: "paperplane") }
                maintenance.tabItem { Label("Bakım", systemImage: "wrench.and.screwdriver") }
                logs.tabItem { Label("Kayıtlar", systemImage: "doc.text") }
            }
            result
            controls
        }
        .padding()
        .frame(minWidth: 560, minHeight: 680)
        .disabled(model.busy)
        .onAppear { model.perform(["status"]) }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !Task.isCancelled { model.perform(["status"]) }
            }
        }
        .onChange(of: model.settings.backgroundEnabled) { _ in
            guard !model.busy else { return }
            model.saveBackgroundImmediately()
        }
    }

    @ViewBuilder private var header: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
            LogoMark(size: 34)
            VStack(alignment: .leading, spacing: 2) {
                Text("Claude Window Starter").font(.headline)
                Text("Mac üzerinde güvenli otomasyon").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Picker("Arka Planda Çalışma", selection: $model.settings.backgroundEnabled) {
                Text("Kapalı").tag(false)
                Text("Açık").tag(true)
            }
            .pickerStyle(.segmented)
            .frame(width: 150)
        }
            if model.settings.backgroundEnabled {
            Text("Ekran kararabilir; boşta uyku önlenir. Pil tüketimi artabilir. Kapak zorunlu uykuya geçirirse iş uyanınca devam eder.")
                .font(.caption)
                .foregroundStyle(.orange)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        HStack(spacing: 8) {
            StatusPill(title: "İnternet", value: model.networkOnline ? "Bağlı" : "Bekliyor", color: model.networkOnline ? .green : .orange)
            StatusPill(title: "Uyku", value: model.powerAssertion ? "Açık" : "Kapalı", color: model.powerAssertion ? .blue : .secondary)
            StatusPill(title: "Otomasyon", value: model.settings.enabled ? "Açık" : "Kapalı", color: model.settings.enabled ? .green : .secondary)
            StatusPill(title: "Telegram", value: model.settings.telegramEnabled ? "Açık" : "Kapalı", color: model.settings.telegramEnabled ? .green : .secondary)
            if model.pendingAutomatic { StatusPill(title: "Çalışma", value: "Bekliyor", color: .orange) }
        }
    }

    private var claude: some View {
        Form {
            Toggle("Günlük otomasyonu etkinleştir", isOn: $model.settings.enabled)
            TextField("Günlük saat (HH:MM)", text: $model.settings.scheduleTime)
            TextField("IANA zaman dilimi", text: $model.settings.timezone)
            Picker("Model", selection: $model.settings.model) {
                ForEach(["auto", "haiku", "sonnet", "opus"], id: \.self, content: Text.init)
            }
            TextField("Prompt", text: $model.settings.prompt, axis: .vertical)
            Stepper("Timeout: \(model.settings.timeout) saniye", value: $model.settings.timeout, in: 10...1800)
            Toggle("İnternet geri geldiğinde bekleyen çalışmayı dene", isOn: $model.settings.catchUp)
            HStack {
                Button("Şimdi çalıştır") { model.perform(["run", "--manual", "--trigger", "macos_ui"]) }
                Button("Dry-run") { model.perform(["run", "--dry-run", "--trigger", "macos_ui"]) }
            }
            Text("Başarılı istek, Claude’un beş saatlik kullanım penceresinin başladığını tek başına kanıtlamaz.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding()
    }

    private var telegram: some View {
        Form {
            Toggle("Telegram botunu etkinleştir", isOn: $model.settings.telegramEnabled)
            SecureField("BotFather tokenı", text: $model.telegramToken)
            Button("Tokenı Keychain’e kaydet") { model.transferTelegramCredential() }
            TextField("İzinli kullanıcı ID", text: $model.settings.telegramUserID)
            TextField("İzinli özel sohbet ID", text: $model.settings.telegramChatID)
            TextField("Bildirim sohbet/kanal ID", text: $model.settings.notificationID)
            Toggle("Bildirim hedefi kanal", isOn: $model.settings.notificationIsChannel)
            Button("Telegram bağlantısını test et") { model.telegramTest() }
            HStack {
                Button("Botu başlat") { model.perform(["service", "telegram", "start"]) }
                Button("Botu durdur") { model.perform(["service", "telegram", "stop"]) }
                Button("Yeniden başlat") { model.perform(["service", "telegram", "restart"]) }
            }
            Text("Komutlar varsayılan olarak yalnızca allowlist içindeki özel sohbetlerde kabul edilir; kanal yalnız bildirim alır.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding()
    }

    private var maintenance: some View {
        Form {
            Button("Durumu yenile") { model.perform(["status"]) }
            Button("Teşhis") { model.perform(["diagnose"]) }
            Button("Sağlık kontrolü") { model.perform(["health"]) }
            Button("Sürümler") { model.perform(["releases"]) }
            Button("Önceki sağlıklı sürüme dön") { model.perform(["rollback", "--yes"]) }
            Text("Bu sürüm yerel release sağlık kontrolü ve rollback akışını kullanır.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding()
    }

    private var logs: some View {
        VStack(alignment: .leading) {
            Button("Kayıtları getir") { model.perform(["logs", "--lines", "80"]) }
            ScrollView {
                Text(model.statusText)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding()
    }

    @ViewBuilder private var result: some View {
        GroupBox("Sonuç") {
            ScrollView {
                Text(model.statusText)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(height: 110)
        }
        if let error = model.lastError {
            Text(error).foregroundStyle(.red).font(.caption)
        }
    }

    private var controls: some View {
        HStack {
            Button("Durum") { model.perform(["status"]) }
            Spacer()
            Button("Ayarları kaydet") { model.saveConfiguration() }.buttonStyle(.borderedProminent)
        }
    }
}

struct StatusPill: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Circle().fill(color).frame(width: 6, height: 6)
            Text("\(title): \(value)").font(.caption2)
        }
        .padding(.horizontal, 7)
        .padding(.vertical, 4)
        .background(.quaternary, in: Capsule())
    }
}

struct LogoMark: View {
    let size: CGFloat

    var body: some View {
        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: size * 0.22)
                .fill(LinearGradient(colors: [Color(red: 0.10, green: 0.12, blue: 0.28), Color(red: 0.18, green: 0.10, blue: 0.34)], startPoint: .topLeading, endPoint: .bottomTrailing))
            RoundedRectangle(cornerRadius: size * 0.12)
                .stroke(Color.cyan.opacity(0.9), lineWidth: size * 0.06)
                .padding(size * 0.18)
            Image(systemName: "sparkle")
                .font(.system(size: size * 0.34, weight: .bold))
                .foregroundStyle(Color.orange)
                .offset(x: size * 0.08, y: -size * 0.05)
        }
        .frame(width: size, height: size)
        .accessibilityLabel("Claude Window Starter logosu")
    }
}
