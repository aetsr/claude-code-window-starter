import SwiftUI

struct ContentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            header
                .padding(.horizontal, 16)
                .padding(.top, 14)
                .padding(.bottom, 10)
            Divider()
            TabView {
                mainTab.tabItem { Label("Otomasyon", systemImage: "sparkles") }
                telegramTab.tabItem { Label("Telegram", systemImage: "paperplane") }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            Divider()
            bottomBar
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
        }
        .frame(minWidth: 580, minHeight: 640)
        .onAppear { model.perform(["status"]) }
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(30))
                if !Task.isCancelled { model.perform(["status"]) }
            }
        }
        .onChange(of: model.settings.backgroundEnabled) { _ in
            guard !model.isSavingBackground else { return }
            model.saveBackgroundImmediately()
        }
    }

    // MARK: – Header

    private var header: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                LogoMark(size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Claude Window Starter").font(.headline)
                    Text("Mac üzerinde güvenli otomasyon").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                // Sleep mode control
                VStack(alignment: .trailing, spacing: 2) {
                    Text("Uyku önleme").font(.caption2).foregroundStyle(.secondary)
                    Picker("", selection: $model.settings.backgroundEnabled) {
                        Text("Kapalı").tag(false)
                        Text("Açık").tag(true)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 130)
                }
            }

            if model.settings.backgroundEnabled {
                HStack(spacing: 6) {
                    Image(systemName: "moon.zzz.fill").foregroundStyle(.orange).font(.caption)
                    Text("Uyku önleme açık — ekran kararabilir, pil tüketimi artabilir.")
                        .font(.caption).foregroundStyle(.orange)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // Status pills
            HStack(spacing: 6) {
                StatusPill(title: "İnternet", value: model.networkOnline ? "Bağlı" : "Yok",
                           color: model.networkOnline ? .green : .orange)
                StatusPill(title: "Uyku", value: model.powerAssertion ? "Açık" : "Kapalı",
                           color: model.powerAssertion ? .blue : .secondary)
                StatusPill(title: "Otomasyon", value: model.settings.enabled ? "Açık" : "Kapalı",
                           color: model.settings.enabled ? .green : .secondary)
                StatusPill(title: "Telegram", value: model.settings.telegramEnabled ? "Açık" : "Kapalı",
                           color: model.settings.telegramEnabled ? .green : .secondary)
                if model.automationBlocked {
                    StatusPill(title: "Müdahale gerekli", value: "!", color: .red)
                }
                Spacer()
                if model.busy {
                    ProgressView().scaleEffect(0.65).frame(width: 16, height: 16)
                }
            }
        }
    }

    // MARK: – Main Tab

    private var mainTab: some View {
        ScrollView {
            VStack(spacing: 12) {
                // General
                settingsCard {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Otomasyon").font(.subheadline).fontWeight(.medium)
                            Text("Zamanlanmış pencere tetiklemelerini etkinleştirir")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Toggle("", isOn: $model.settings.enabled).labelsHidden()
                    }
                    Divider()
                    HStack {
                        Text("Zaman dilimi").font(.subheadline)
                        Spacer()
                        TextField("Europe/Istanbul", text: $model.settings.timezone)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 180)
                            .multilineTextAlignment(.trailing)
                    }
                }

                // 5-hour calibration
                calibrationCard(
                    title: "5 Saatlik Limit",
                    icon: "clock.fill",
                    isEnabled: $model.settings.fiveHourEnabled,
                    isCalibrated: model.fiveHourIsCalibrated,
                    countdown: model.fiveHourCountdown,
                    nextRunText: model.fiveHourNextRunText,
                    lastResult: model.fiveHourLastResultText,
                    calibrationNeeded: model.fiveHourCalibrationNeeded,
                    calibrationError: model.fiveHourCalibrationError
                ) {
                    // Time-remaining input for 5-hour
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.fiveHourIsCalibrated ? "Kalan süreyi güncelle" : "Şu an ne kadar süre kaldı?")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 10) {
                            HStack(spacing: 4) {
                                TextField("", value: $model.fiveHourRemainingHours, format: .number)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 44)
                                    .multilineTextAlignment(.center)
                                Stepper("", value: $model.fiveHourRemainingHours, in: 0...4).labelsHidden()
                                Text("saat").font(.caption).foregroundStyle(.secondary)
                            }
                            HStack(spacing: 4) {
                                TextField("", value: $model.fiveHourRemainingMinutes, format: .number)
                                    .textFieldStyle(.roundedBorder)
                                    .frame(width: 44)
                                    .multilineTextAlignment(.center)
                                Stepper("", value: $model.fiveHourRemainingMinutes, in: 0...59).labelsHidden()
                                Text("dakika").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Button(model.fiveHourIsCalibrated ? "Güncelle" : "Kaydet") {
                                model.saveWindowAnchor("five_hour")
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
                        }
                    }
                }

                // Weekly calibration
                calibrationCard(
                    title: "Haftalık Limit",
                    icon: "calendar",
                    isEnabled: $model.settings.weeklyEnabled,
                    isCalibrated: model.weeklyIsCalibrated,
                    countdown: model.weeklyCountdown,
                    nextRunText: model.weeklyNextRunText,
                    lastResult: model.weeklyLastResultText,
                    calibrationNeeded: model.weeklyCalibrationNeeded,
                    calibrationError: model.weeklyCalibrationError
                ) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.weeklyIsCalibrated ? "Reset zamanını güncelle" : "Son reset ne zamandı?")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 8) {
                            DatePicker("", selection: $model.weeklyAnchorDate,
                                       displayedComponents: [.date, .hourAndMinute])
                                .datePickerStyle(.compact)
                                .labelsHidden()
                            Spacer()
                            Button(model.weeklyIsCalibrated ? "Güncelle" : "Kaydet") {
                                model.saveWindowAnchor("weekly")
                            }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
                        }
                    }
                }

                // Claude settings
                settingsCard {
                    HStack {
                        Text("Model").font(.subheadline)
                        Spacer()
                        Picker("", selection: $model.settings.model) {
                            ForEach(["auto", "haiku", "sonnet", "opus"], id: \.self, content: Text.init)
                        }
                        .frame(width: 120)
                    }
                    Divider()
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Prompt").font(.subheadline)
                        TextField("Prompt girin…", text: $model.settings.prompt, axis: .vertical)
                            .textFieldStyle(.roundedBorder)
                            .lineLimit(3...6)
                    }
                    Divider()
                    HStack {
                        Text("Timeout").font(.subheadline)
                        Spacer()
                        Stepper("\(model.settings.timeout) sn", value: $model.settings.timeout, in: 10...1800)
                    }
                    Divider()
                    HStack {
                        Button("Şimdi çalıştır") { model.perform(["run", "--trigger", "macos_ui"]) }
                            .disabled(model.busy)
                        Spacer()
                    }
                }
            }
            .padding(16)
        }
    }

    // MARK: – Telegram Tab

    private var telegramTab: some View {
        ScrollView {
            VStack(spacing: 12) {
                // Bot config
                settingsCard {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Telegram Botu").font(.subheadline).fontWeight(.medium)
                            Text("Kapak kapansa bile Telegram üzerinden tam kontrol")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Toggle("", isOn: $model.settings.telegramEnabled).labelsHidden()
                    }
                }

                settingsCard {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Bot Token", systemImage: "key.fill").font(.subheadline).fontWeight(.medium)
                        HStack(spacing: 8) {
                            SecureField("BotFather'dan aldığınız token", text: $model.telegramToken)
                                .textFieldStyle(.roundedBorder)
                            Button("Kaydet") { model.transferTelegramCredential() }
                                .disabled(model.telegramToken.isEmpty)
                        }
                        Text("Token bir kez kaydedilir, ekranda gösterilmez.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                settingsCard {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Erişim Kontrolü", systemImage: "person.badge.shield.checkmark.fill")
                            .font(.subheadline).fontWeight(.medium)
                        HStack {
                            Text("Kullanıcı ID").font(.caption).foregroundStyle(.secondary).frame(width: 110, alignment: .leading)
                            TextField("Sayısal ID", text: $model.settings.telegramUserID)
                                .textFieldStyle(.roundedBorder)
                        }
                        HStack {
                            Text("Özel Sohbet ID").font(.caption).foregroundStyle(.secondary).frame(width: 110, alignment: .leading)
                            TextField("Sayısal ID", text: $model.settings.telegramChatID)
                                .textFieldStyle(.roundedBorder)
                        }
                        HStack {
                            Text("Bildirim Hedefi").font(.caption).foregroundStyle(.secondary).frame(width: 110, alignment: .leading)
                            TextField("Sohbet veya kanal ID", text: $model.settings.notificationID)
                                .textFieldStyle(.roundedBorder)
                        }
                        Toggle("Bildirim hedefi kanal", isOn: $model.settings.notificationIsChannel)
                            .font(.subheadline)
                    }
                }

                settingsCard {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Güvenli Eşleştirme", systemImage: "link.badge.plus")
                            .font(.subheadline).fontWeight(.medium)
                        Text("Bota aşağıdaki komutu gönderin:")
                            .font(.caption).foregroundStyle(.secondary)
                        Text("/pair \(model.telegramPairCode)")
                            .font(.system(.body, design: .monospaced))
                            .padding(8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                            .textSelection(.enabled)
                        HStack(spacing: 8) {
                            Button("Eşleştir ve etkinleştir") { model.pairTelegram() }
                                .buttonStyle(.borderedProminent)
                                .disabled(model.busy)
                            Button("Yeni kod") { model.renewTelegramPairCode() }
                        }
                        Text("Eşleştirme sonrası kullanıcı ve sohbet ID'leri otomatik doldurulur.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                settingsCard {
                    VStack(alignment: .leading, spacing: 10) {
                        Label("Bot Servisi", systemImage: "gearshape.2.fill")
                            .font(.subheadline).fontWeight(.medium)
                        HStack(spacing: 8) {
                            Button("Başlat") { model.perform(["service", "telegram", "start"]) }
                                .disabled(model.busy)
                            Button("Durdur") { model.perform(["service", "telegram", "stop"]) }
                                .disabled(model.busy)
                            Button("Yeniden başlat") { model.perform(["service", "telegram", "restart"]) }
                                .disabled(model.busy)
                            Spacer()
                            Button("Bağlantıyı test et") { model.telegramTest() }
                                .disabled(model.busy)
                        }
                        Text("Kapak kapandığında uyku önleme açıksa bot çalışmaya devam eder. Tüm komutlar (/run, /status, /calibrate_5h, /calibrate_weekly) Telegram üzerinden kullanılabilir.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            .padding(16)
        }
    }

    // MARK: – Bottom bar

    private var bottomBar: some View {
        HStack(spacing: 8) {
            // Result / error inline
            Group {
                if let error = model.lastError {
                    Label(error, systemImage: "exclamationmark.triangle.fill")
                        .foregroundStyle(.red)
                        .font(.caption)
                        .lineLimit(2)
                } else if !model.statusText.isEmpty && model.statusText != "Henüz kontrol edilmedi" {
                    Text(model.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button("Durum") { model.perform(["status"]) }
                .disabled(model.busy)
            Button("Ayarları kaydet") { model.saveConfiguration() }
                .buttonStyle(.borderedProminent)
                .disabled(model.busy)
        }
    }

    // MARK: – Reusable components

    @ViewBuilder
    private func settingsCard<Content: View>(@ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            content()
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.background, in: RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(.separator, lineWidth: 0.5))
    }

    @ViewBuilder
    private func calibrationCard<Input: View>(
        title: String,
        icon: String,
        isEnabled: Binding<Bool>,
        isCalibrated: Bool,
        countdown: String,
        nextRunText: String,
        lastResult: String?,
        calibrationNeeded: Bool,
        calibrationError: String,
        @ViewBuilder input: () -> Input
    ) -> some View {
        settingsCard {
            // Title row
            HStack(spacing: 8) {
                Image(systemName: icon).foregroundStyle(.blue)
                Text(title).font(.subheadline).fontWeight(.medium)
                Spacer()
                Toggle("", isOn: isEnabled).labelsHidden()
            }

            // Countdown row (only when calibrated)
            if isCalibrated {
                HStack {
                    Text(countdown)
                        .font(.system(.title3, design: .monospaced))
                        .fontWeight(.semibold)
                    Spacer()
                    Text(nextRunText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
                .padding(.horizontal, 10)
                .background(.quaternary, in: RoundedRectangle(cornerRadius: 8))
            }

            // Warning: enabled but not calibrated
            if isEnabled.wrappedValue && !isCalibrated {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.red).font(.caption)
                    Text("Otomasyon için önce kalibre edilmeli").font(.caption).foregroundStyle(.red)
                }
            }

            Divider()

            // Input section
            input()

            // Last result
            if let result = lastResult {
                Text(result).font(.caption).foregroundStyle(.secondary)
            }

            // Calibration error banner
            if calibrationNeeded {
                HStack(spacing: 6) {
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange).font(.caption)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Kalibrasyon hatası").fontWeight(.medium).font(.caption)
                        if !calibrationError.isEmpty {
                            Text(calibrationError).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(8)
                .background(.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 6))
            }
        }
    }
}

// MARK: – Supporting Views

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
        .padding(.vertical, 3)
        .background(.quaternary, in: Capsule())
    }
}

struct LogoMark: View {
    let size: CGFloat

    var body: some View {
        ZStack(alignment: .topTrailing) {
            RoundedRectangle(cornerRadius: size * 0.22)
                .fill(LinearGradient(
                    colors: [Color(red: 0.10, green: 0.12, blue: 0.28),
                             Color(red: 0.18, green: 0.10, blue: 0.34)],
                    startPoint: .topLeading, endPoint: .bottomTrailing))
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
