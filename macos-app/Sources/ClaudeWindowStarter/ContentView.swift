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
                mainTab.tabItem { Label("Automation", systemImage: "sparkles") }
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
        .onChange(of: model.settings.enabled) { _ in model.saveConfiguration() }
        .onChange(of: model.settings.fiveHourEnabled) { _ in model.saveConfiguration() }
        .onChange(of: model.settings.weeklyEnabled) { _ in model.saveConfiguration() }
        .onChange(of: model.settings.telegramEnabled) { _ in model.saveConfiguration() }
        .onChange(of: model.settings.model) { _ in model.saveConfiguration() }
    }

    // MARK: – Header

    private var header: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                LogoMark(size: 32)
                VStack(alignment: .leading, spacing: 1) {
                    Text("Claude Window Starter").font(.headline)
                    Text("Secure automation on Mac").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                // Sleep mode control
                VStack(alignment: .trailing, spacing: 2) {
                    Text("Sleep prevention").font(.caption2).foregroundStyle(.secondary)
                    Picker("", selection: $model.settings.backgroundEnabled) {
                        Text("Off").tag(false)
                        Text("On").tag(true)
                    }
                    .pickerStyle(.segmented)
                    .frame(width: 130)
                }
            }

            if model.settings.backgroundEnabled {
                HStack(spacing: 6) {
                    Image(systemName: "moon.zzz.fill").foregroundStyle(.orange).font(.caption)
                    Text("Sleep prevention is on — screen may dim, battery usage may increase.")
                        .font(.caption).foregroundStyle(.orange)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            // Status pills
            HStack(spacing: 6) {
                StatusPill(title: "Internet", value: model.networkOnline ? "Connected" : "None",
                           color: model.networkOnline ? .green : .orange)
                StatusPill(title: "Sleep", value: model.powerAssertion ? "On" : "Off",
                           color: model.powerAssertion ? .blue : .secondary)
                StatusPill(title: "Automation", value: model.settings.enabled ? "On" : "Off",
                           color: model.settings.enabled ? .green : .secondary)
                StatusPill(title: "Telegram", value: model.telegramBotRunning ? "Running" : (model.settings.telegramEnabled ? "Waiting" : "Off"),
                           color: model.telegramBotRunning ? .green : (model.settings.telegramEnabled ? .orange : .secondary))
                if model.automationBlocked {
                    StatusPill(title: "Action required", value: "!", color: .red)
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
                            Text("Automation").font(.subheadline).fontWeight(.medium)
                            Text("Enables scheduled window triggers")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Toggle("", isOn: $model.settings.enabled).labelsHidden()
                    }
                    Divider()
                    HStack {
                        Text("Timezone").font(.subheadline)
                        Spacer()
                        TextField("Europe/Istanbul", text: $model.settings.timezone)
                            .textFieldStyle(.roundedBorder)
                            .frame(width: 180)
                            .multilineTextAlignment(.trailing)
                    }
                }

                // Adaptive five-hour planner
                settingsCard {
                    HStack {
                        Label("Dinamik 5 Saat Planlayıcısı", systemImage: "clock.arrow.2.circlepath")
                            .font(.subheadline).fontWeight(.semibold)
                        Spacer()
                        Toggle("", isOn: $model.settings.fiveHourEnabled).labelsHidden()
                    }
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Yoğun başlangıç").font(.caption).foregroundStyle(.secondary)
                            TextField("08:00", text: $model.settings.busyStartLocal)
                                .textFieldStyle(.roundedBorder).frame(width: 90)
                        }
                        Image(systemName: "arrow.right").foregroundStyle(.secondary)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("Yoğun bitiş").font(.caption).foregroundStyle(.secondary)
                            TextField("17:00", text: $model.settings.busyEndLocal)
                                .textFieldStyle(.roundedBorder).frame(width: 90)
                        }
                        Spacer()
                        Button("Kaydet") {
                            model.settings.fiveHourMode = "adaptive"
                            model.saveConfiguration()
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    Text("Hafta içi · Maksimum kota")
                        .font(.caption).foregroundStyle(.secondary)
                    Divider()
                    LabeledContent("Bugünkü anchorlar", value: model.todayAnchorPreview)
                    LabeledContent("Gözlenen gerçek reset", value: model.observedResetText)
                    LabeledContent("Kaynak / tazelik", value: model.usageSourceText)
                    LabeledContent("Plan güveni", value: model.adaptiveConfidence)
                    HStack {
                        Button("Şimdi senkronize et") { model.syncUsage() }
                            .disabled(model.busy)
                        Spacer()
                    }
                    DisclosureGroup("Manuel override") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Claude penceresindeki kalan süreyi elle girerek sabit anchor kullanın.")
                                .font(.caption).foregroundStyle(.secondary)
                            HStack {
                                Stepper("\(model.fiveHourRemainingHours) sa", value: $model.fiveHourRemainingHours, in: 0...4)
                                Stepper("\(model.fiveHourRemainingMinutes) dk", value: $model.fiveHourRemainingMinutes, in: 0...59)
                                Spacer()
                                Button("Manuel ayarla") {
                                    model.settings.fiveHourMode = "manual"
                                    model.saveConfiguration()
                                    model.saveWindowAnchor("five_hour")
                                }
                            }
                        }
                        .padding(.top, 6)
                    }
                }

                // Weekly calibration
                calibrationCard(
                    title: "Weekly Limit",
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
                        Text(model.weeklyIsCalibrated ? "Update reset time" : "When was the last reset?")
                            .font(.caption).foregroundStyle(.secondary)
                        HStack(spacing: 8) {
                            DatePicker("", selection: $model.weeklyAnchorDate,
                                       displayedComponents: [.date, .hourAndMinute])
                                .datePickerStyle(.compact)
                                .labelsHidden()
                            Spacer()
                            Button(model.weeklyIsCalibrated ? "Update" : "Save") {
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
                        TextField("Enter prompt…", text: $model.settings.prompt, axis: .vertical)
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
                        Button("Run now") { model.perform(["run", "--trigger", "macos_ui"]) }
                            .disabled(model.busy)
                        Spacer()
                        Button("Save") { model.saveConfiguration() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
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
                // ── Bot Status & Enable ───────────────────────────────────────
                settingsCard {
                    HStack(spacing: 12) {
                        ZStack {
                            Circle()
                                .fill(model.telegramBotRunning ? Color.green.opacity(0.15) : Color.secondary.opacity(0.1))
                                .frame(width: 40, height: 40)
                            Image(systemName: "paperplane.fill")
                                .foregroundStyle(model.telegramBotRunning ? .green : .secondary)
                                .font(.system(size: 18))
                        }
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Telegram Bot").font(.subheadline).fontWeight(.semibold)
                            HStack(spacing: 5) {
                                Circle()
                                    .fill(model.telegramBotRunning ? Color.green : Color.secondary)
                                    .frame(width: 6, height: 6)
                                Text(model.telegramBotRunning ? "Running" : "Stopped")
                                    .font(.caption)
                                    .foregroundStyle(model.telegramBotRunning ? .green : .secondary)
                            }
                        }
                        Spacer()
                        Toggle("", isOn: $model.settings.telegramEnabled).labelsHidden()
                    }
                    if model.settings.telegramEnabled {
                        Divider()
                        Text("When the lid is closed, the bot continues running if sleep prevention is on.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                // ── Service Controls ─────────────────────────────────────────
                settingsCard {
                    HStack(spacing: 8) {
                        Button {
                            model.perform(["service", "telegram", "start"])
                        } label: {
                            Label("Start", systemImage: "play.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .disabled(model.busy || model.telegramBotRunning)
                        .buttonStyle(.bordered)

                        Button {
                            model.perform(["service", "telegram", "stop"])
                        } label: {
                            Label("Stop", systemImage: "stop.fill")
                                .frame(maxWidth: .infinity)
                        }
                        .disabled(model.busy || !model.telegramBotRunning)
                        .buttonStyle(.bordered)
                        .tint(.red)

                        Button {
                            model.perform(["service", "telegram", "restart"])
                        } label: {
                            Label("Restart", systemImage: "arrow.clockwise")
                                .frame(maxWidth: .infinity)
                        }
                        .disabled(model.busy)
                        .buttonStyle(.bordered)
                    }
                    Divider()
                    HStack {
                        Button("Test connection") { model.telegramTest() }
                            .disabled(model.busy)
                        Spacer()
                    }
                }

                // ── Bot Token ────────────────────────────────────────────────
                settingsCard {
                    HStack {
                        Label("Bot Token", systemImage: "key.fill")
                            .font(.subheadline).fontWeight(.semibold)
                        Spacer()
                        HStack(spacing: 4) {
                            Circle()
                                .fill(model.telegramTokenConfigured ? Color.green : Color.orange)
                                .frame(width: 7, height: 7)
                            Text(model.telegramTokenConfigured ? "Saved" : "Not saved")
                                .font(.caption2)
                                .foregroundStyle(model.telegramTokenConfigured ? .green : .orange)
                        }
                    }
                    HStack(spacing: 8) {
                        SecureField("Token from BotFather", text: $model.telegramToken)
                            .textFieldStyle(.roundedBorder)
                        Button("Save") { model.transferTelegramCredential() }
                            .disabled(model.telegramToken.isEmpty)
                            .buttonStyle(.borderedProminent)
                    }
                    if !model.telegramTokenConfigured {
                        HStack(spacing: 6) {
                            Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange).font(.caption)
                            Text("Without a token, the bot cannot start and pairing cannot be done.")
                                .font(.caption).foregroundStyle(.orange)
                        }
                    } else {
                        Text("Token has been securely saved to Keychain.")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                // ── Pairing ──────────────────────────────────────────────────
                settingsCard {
                    Label("Secure Pairing", systemImage: "link.badge.plus")
                        .font(.subheadline).fontWeight(.semibold)
                    Text("Send this command to the bot:").font(.caption).foregroundStyle(.secondary)
                    Text("/pair \(model.telegramPairCode)")
                        .font(.system(.body, design: .monospaced))
                        .padding(8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(.quaternary, in: RoundedRectangle(cornerRadius: 6))
                        .textSelection(.enabled)
                    HStack(spacing: 8) {
                        Button("Pair and activate") { model.pairTelegram() }
                            .buttonStyle(.borderedProminent)
                            .disabled(model.busy)
                        Button("New code") { model.renewTelegramPairCode() }
                    }
                    Text("When pairing is complete, user and chat IDs are added automatically.")
                        .font(.caption).foregroundStyle(.secondary)
                }

                // ── User Management ──────────────────────────────────────────
                settingsCard {
                    HStack {
                        Label("Authorized Users", systemImage: "person.2.fill")
                            .font(.subheadline).fontWeight(.semibold)
                        Spacer()
                        Button { model.loadTelegramUsers() } label: {
                            Image(systemName: "arrow.clockwise").font(.caption)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(.secondary)
                    }

                    if model.telegramUserList.isEmpty {
                        Text("No users added yet")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 4)
                    } else {
                        VStack(spacing: 4) {
                            ForEach(model.telegramUserList, id: \.self) { uid in
                                HStack {
                                    Image(systemName: "person.fill").foregroundStyle(.blue).font(.caption)
                                    Text(String(uid))
                                        .font(.system(.body, design: .monospaced))
                                        .foregroundStyle(.primary)
                                    Spacer()
                                    Button {
                                        model.removeTelegramUser(uid)
                                    } label: {
                                        Image(systemName: "minus.circle.fill").foregroundStyle(.red)
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(model.busy)
                                }
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                            }
                        }
                    }

                    Divider()
                    HStack(spacing: 8) {
                        TextField("Add user ID", text: $model.newTelegramUserID)
                            .textFieldStyle(.roundedBorder)
                        Button {
                            model.addTelegramUser()
                        } label: {
                            Image(systemName: "plus.circle.fill").foregroundStyle(.green)
                        }
                        .buttonStyle(.plain)
                        .disabled(model.busy || model.newTelegramUserID.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }

                // ── Chat Management ──────────────────────────────────────────
                settingsCard {
                    Label("Authorized Chats", systemImage: "bubble.left.and.bubble.right.fill")
                        .font(.subheadline).fontWeight(.semibold)

                    if model.telegramChatList.isEmpty {
                        Text("No chats added yet")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.vertical, 4)
                    } else {
                        VStack(spacing: 4) {
                            ForEach(model.telegramChatList, id: \.self) { cid in
                                HStack {
                                    Image(systemName: "bubble.left.fill").foregroundStyle(.teal).font(.caption)
                                    Text(String(cid))
                                        .font(.system(.body, design: .monospaced))
                                    Spacer()
                                    Button {
                                        model.removeTelegramChat(cid)
                                    } label: {
                                        Image(systemName: "minus.circle.fill").foregroundStyle(.red)
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(model.busy)
                                }
                                .padding(.horizontal, 8)
                                .padding(.vertical, 4)
                                .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 6))
                            }
                        }
                    }

                    Divider()
                    HStack(spacing: 8) {
                        TextField("Add chat ID", text: $model.newTelegramChatID)
                            .textFieldStyle(.roundedBorder)
                        Button {
                            model.addTelegramChat()
                        } label: {
                            Image(systemName: "plus.circle.fill").foregroundStyle(.green)
                        }
                        .buttonStyle(.plain)
                        .disabled(model.busy || model.newTelegramChatID.trimmingCharacters(in: .whitespaces).isEmpty)
                    }
                }

                // ── Notification Settings ────────────────────────────────────
                settingsCard {
                    Label("Notification Settings", systemImage: "bell.fill")
                        .font(.subheadline).fontWeight(.semibold)
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Notification Target").font(.caption).foregroundStyle(.secondary)
                        TextField("Chat or channel ID", text: $model.settings.notificationID)
                            .textFieldStyle(.roundedBorder)
                    }
                    Toggle("Notification target is a channel", isOn: $model.settings.notificationIsChannel)
                        .font(.subheadline)
                    Text("Notifications are sent to this target (results, errors, calibration warnings).")
                        .font(.caption).foregroundStyle(.secondary)
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
                } else if !model.statusText.isEmpty && model.statusText != "Not checked yet" {
                    Text(model.statusText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button("Refresh") { model.perform(["status"]) }
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
                    Text("Must be calibrated before automation can run").font(.caption).foregroundStyle(.red)
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
                        Text("Calibration error").fontWeight(.medium).font(.caption)
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
        .accessibilityLabel("Claude Window Starter logo")
    }
}
