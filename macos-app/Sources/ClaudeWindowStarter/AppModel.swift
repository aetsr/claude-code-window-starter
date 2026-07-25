import AppKit
import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var settings: ClientSettings
    @Published var statusText = "Henüz kontrol edilmedi"
    @Published var busy = false
    @Published var lastError: String?
    @Published var telegramToken = ""
    @Published var networkOnline = false
    @Published var powerAssertion = false
    @Published var pendingAutomatic = false
    @Published var automationBlocked = false
    @Published var nextRunText = "İlk kontrol bekleniyor"
    @Published var usageWindowText = "Henüz doğrulanmadı"
    @Published var claudeAuthStatus = "unknown"
    @Published var claudeLoginCommand = "claude auth login"
    @Published var claudeAuthHint = ""
    @Published var telegramPairCode = String(UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(8)).uppercased()

    // Window countdown and calibration
    @Published var fiveHourCountdown = "—"
    @Published var fiveHourNextRunText = "Henüz kurulmadı"
    @Published var fiveHourLastResultText: String? = nil
    @Published var fiveHourCalibrationNeeded = false
    @Published var fiveHourCalibrationError = ""
    @Published var weeklyCountdown = "—"
    @Published var weeklyNextRunText = "Henüz kurulmadı"
    @Published var weeklyLastResultText: String? = nil
    @Published var weeklyCalibrationNeeded = false
    @Published var weeklyCalibrationError = ""
    @Published var calibrationDate = Date()

    private let backend = BackendClient()

    init(settings: ClientSettings = SettingsStore.load()) {
        self.settings = settings
    }

    var statusIcon: String {
        if lastError != nil { return "exclamationmark.triangle" }
        if busy { return "clock" }
        return settings.backgroundEnabled ? "moon.stars.fill" : "rectangle.and.sparkles"
    }

    func perform(_ arguments: [String]) {
        busy = true
        lastError = nil
        Task {
            defer { busy = false }
            do {
                let result = try await backend.command(arguments: arguments)
                statusText = renderResult(arguments: arguments, result: result)
                if arguments.first == "status" {
                    parseStatus(result.data)
                } else if arguments.first == "config", arguments.dropFirst().first == "get" {
                    parseConfig(result.data)
                } else if arguments.first == "run" {
                    parseRunResult(result.data)
                    await refreshStatus(silent: true)
                }
            } catch {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func loadFromBackend() {
        busy = true
        lastError = nil
        Task {
            defer { busy = false }
            do {
                let config = try await backend.command(arguments: ["config", "get"])
                parseConfig(config.data)
                await refreshStatus(silent: true)
                statusText = "Ayarlar backend’den yüklendi."
            } catch {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func refreshStatus(silent: Bool) async {
        do {
            let result = try await backend.command(arguments: ["status"])
            parseStatus(result.data)
            if !silent {
                statusText = renderResult(arguments: ["status"], result: result)
            }
        } catch {
            if !silent {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func saveConfiguration() {
        let trimmedUserID = settings.telegramUserID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedChatID = settings.telegramChatID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNotificationID = settings.notificationID.trimmingCharacters(in: .whitespacesAndNewlines)
        let userID = Int64(trimmedUserID)
        let chatID = Int64(trimmedChatID)
        let notificationID = Int64(trimmedNotificationID)
        if settings.telegramEnabled && (userID == nil || chatID == nil) {
            lastError = "Telegram etkinse izinli kullanıcı ve özel sohbet ID alanları sayısal olmalıdır."
            return
        }
        if !trimmedNotificationID.isEmpty && notificationID == nil {
            lastError = "Bildirim sohbet/kanal ID alanı sayısal olmalıdır."
            return
        }
        busy = true
        lastError = nil
        let document: [String: Any] = [
            "enabled": settings.enabled,
            "background_enabled": settings.backgroundEnabled,
            "schedule_time": settings.scheduleTime,
            "timezone": settings.timezone,
            "model": settings.model,
            "prompt": settings.prompt,
            "timeout_seconds": settings.timeout,
            "allow_catch_up": settings.catchUp,
            "windows": [
                "five_hour": [
                    "enabled": settings.fiveHourEnabled,
                    "anchor_iso": settings.fiveHourAnchorISO,
                    "interval_minutes": settings.fiveHourIntervalMinutes,
                ],
                "weekly": [
                    "enabled": settings.weeklyEnabled,
                    "anchor_iso": settings.weeklyAnchorISO,
                    "interval_minutes": settings.weeklyIntervalMinutes,
                ],
            ],
            "telegram": [
                "enabled": settings.telegramEnabled,
                "allowed_user_ids": userID.map { [$0] } ?? [],
                "allowed_chat_ids": chatID.map { [$0] } ?? [],
                "notification_chat_id": settings.notificationIsChannel ? NSNull() : (notificationID.map { $0 as Any } ?? NSNull()),
                "notification_channel_id": settings.notificationIsChannel ? (notificationID.map { $0 as Any } ?? NSNull()) : NSNull(),
            ],
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: document)
            Task {
                defer { busy = false }
                do {
                    let result = try await backend.applyConfig(data: data)
                    try SettingsStore.save(settings)
                    statusText = renderResult(arguments: ["config", "patch-stdin"], result: result)
                    await refreshStatus(silent: true)
                } catch {
                    lastError = error.localizedDescription
                    statusText = error.localizedDescription
                }
            }
        } catch {
            busy = false
            lastError = "Ayarlar kaydedilemedi."
        }
    }

    func saveBackgroundImmediately() {
        saveConfiguration()
    }

    func transferTelegramCredential() {
        guard !telegramToken.isEmpty else {
            lastError = "Telegram tokenını girin."
            return
        }
        do {
            try KeychainStore.save(telegramToken, account: "telegram_token")
            telegramToken = ""
            statusText = "Telegram tokenı Keychain’e kaydedildi; değeri tekrar gösterilmeyecek."
        } catch {
            lastError = error.localizedDescription
        }
    }

    func telegramTest() {
        busy = true
        lastError = nil
        Task {
            defer { busy = false }
            do {
                let result = try await backend.telegramTest()
                if case .object(let object)? = result.data,
                   case .bool(let messageSent)? = object["message_sent"] {
                    statusText = messageSent
                        ? "Telegram bağlantısı ve test mesajı başarılı."
                        : "Telegram Bot API bağlantısı başarılı. Mesaj testi için önce özel sohbeti eşleştirin."
                } else {
                    statusText = "Telegram Bot API bağlantısı başarılı."
                }
            } catch {
                lastError = error.localizedDescription
            }
        }
    }

    func renewTelegramPairCode() {
        telegramPairCode = String(
            UUID().uuidString.replacingOccurrences(of: "-", with: "").prefix(8)
        ).uppercased()
    }

    func calibrateWindow(_ windowType: String) {
        let formatter = ISO8601DateFormatter()
        let isoString = formatter.string(from: calibrationDate)
        perform(["calibrate", "--window-type", windowType, "--anchor", isoString])
    }

    func pairTelegram() {
        busy = true
        lastError = nil
        Task {
            defer { busy = false }
            do {
                let result = try await backend.telegramPair(code: telegramPairCode)
                guard case .object(let object)? = result.data,
                      case .number(let userID)? = object["user_id"],
                      case .number(let chatID)? = object["chat_id"] else {
                    throw ProcessRunnerError.invalidOutput
                }
                settings.telegramUserID = String(Int64(userID))
                settings.telegramChatID = String(Int64(chatID))
                settings.notificationID = String(Int64(chatID))
                settings.telegramEnabled = true
                var parts = ["Telegram özel sohbeti eşleştirildi ve bot etkinleştirildi."]
                if case .bool(let restarted)? = object["service_restarted"], !restarted {
                    parts.append("Servis yeniden başlatılamadı; Bakım sekmesinden telegram servisini yeniden başlatın.")
                }
                statusText = parts.joined(separator: " ")
                try SettingsStore.save(settings)
                await refreshStatus(silent: true)
                renewTelegramPairCode()
            } catch {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func parseStatus(_ value: JSONValue?) {
        guard case .object(let object) = value else { return }
        if case .bool(let value)? = object["enabled"] { settings.enabled = value }
        if case .bool(let value)? = object["background_enabled"] { settings.backgroundEnabled = value }
        if case .bool(let value)? = object["telegram_enabled"] { settings.telegramEnabled = value }

        // Parse window status
        if case .object(let windows)? = object["windows"] {
            parseWindowStatus("five_hour", windows["five_hour"])
            parseWindowStatus("weekly", windows["weekly"])
        }

        if case .object(let health)? = object["health"], case .object(let checks)? = health["checks"] {
            if case .object(let background)? = checks["background"] {
                if case .bool(let value)? = background["network_online"] { networkOnline = value }
                if case .bool(let value)? = background["power_assertion"] { powerAssertion = value }
            }
            if case .object(let claude)? = checks["claude"] {
                if case .string(let auth)? = claude["auth_status"] { claudeAuthStatus = auth }
                if case .string(let command)? = claude["login_command"] { claudeLoginCommand = command }
                claudeAuthHint = claudeAuthStatus == "authenticated"
                    ? "Claude oturumu doğrulandı."
                    : "Claude oturumu hazır değil. Terminalde `\(claudeLoginCommand)` çalıştırın."
            }
        }
        if case .object? = object["pending_automatic"] { pendingAutomatic = true } else { pendingAutomatic = false }
        if case .object? = object["automatic_blocked"] { automationBlocked = true } else { automationBlocked = false }
    }

    private func parseWindowStatus(_ windowType: String, _ value: JSONValue?) {
        guard case .object(let window) = value else { return }

        let countdownKey = windowType == "five_hour" ? "fiveHourCountdown" : "weeklyCountdown"
        let nextRunKey = windowType == "five_hour" ? "fiveHourNextRunText" : "weeklyNextRunText"
        let lastResultKey = windowType == "five_hour" ? "fiveHourLastResultText" : "weeklyLastResultText"
        let calibrationNeededKey = windowType == "five_hour" ? "fiveHourCalibrationNeeded" : "weeklyCalibrationNeeded"
        let calibrationErrorKey = windowType == "five_hour" ? "fiveHourCalibrationError" : "weeklyCalibrationError"

        if case .string(let countdown)? = window["countdown"] {
            if windowType == "five_hour" { fiveHourCountdown = countdown }
            else { weeklyCountdown = countdown }
        }

        if case .string(let nextRun)? = window["next_run_at"] {
            let formatter = ISO8601DateFormatter()
            if let date = formatter.date(from: nextRun) {
                let display = formatDateTime(date)
                if windowType == "five_hour" { fiveHourNextRunText = display }
                else { weeklyNextRunText = display }
            }
        }

        if case .object(let result)? = window["last_result"] {
            if case .string(let status)? = result["status"], status == "success" {
                let model = (result["selected_model"]).flatMap {
                    if case .string(let v) = $0 { return v }
                    return nil
                } ?? "auto"
                let summary = (result["response_summary"]).flatMap {
                    if case .string(let v) = $0 { return v }
                    return nil
                } ?? ""
                let text = "✓ \(model)\(summary.isEmpty ? "" : " - \(summary)")"
                if windowType == "five_hour" { fiveHourLastResultText = text }
                else { weeklyLastResultText = text }
            }
        }

        if case .object(let calibration)? = window["calibration_needed"] {
            let error = (calibration["error_message"]).flatMap {
                if case .string(let v) = $0 { return v }
                return nil
            } ?? ""
            if windowType == "five_hour" {
                fiveHourCalibrationNeeded = true
                fiveHourCalibrationError = error
            } else {
                weeklyCalibrationNeeded = true
                weeklyCalibrationError = error
            }
        } else {
            if windowType == "five_hour" {
                fiveHourCalibrationNeeded = false
                fiveHourCalibrationError = ""
            } else {
                weeklyCalibrationNeeded = false
                weeklyCalibrationError = ""
            }
        }
    }

    private func formatDateTime(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter.string(from: date)
    }

    func parseConfig(_ value: JSONValue?) {
        guard case .object(let object) = value else { return }
        if case .string(let value)? = object["schedule_time"] { settings.scheduleTime = value }
        if case .string(let value)? = object["timezone"] { settings.timezone = value }
        if case .string(let value)? = object["model"] { settings.model = value }
        if case .string(let value)? = object["prompt"] { settings.prompt = value }
        if case .number(let value)? = object["timeout_seconds"] { settings.timeout = Int(value) }
        if case .bool(let value)? = object["enabled"] { settings.enabled = value }
        if case .bool(let value)? = object["background_enabled"] { settings.backgroundEnabled = value }
        if case .bool(let value)? = object["allow_catch_up"] { settings.catchUp = value }

        // Parse window config
        if case .object(let windows)? = object["windows"] {
            if case .object(let fiveHour)? = windows["five_hour"] {
                if case .bool(let value)? = fiveHour["enabled"] { settings.fiveHourEnabled = value }
                if case .string(let value)? = fiveHour["anchor_iso"] { settings.fiveHourAnchorISO = value }
                if case .number(let value)? = fiveHour["interval_minutes"] { settings.fiveHourIntervalMinutes = Int(value) }
            }
            if case .object(let weekly)? = windows["weekly"] {
                if case .bool(let value)? = weekly["enabled"] { settings.weeklyEnabled = value }
                if case .string(let value)? = weekly["anchor_iso"] { settings.weeklyAnchorISO = value }
                if case .number(let value)? = weekly["interval_minutes"] { settings.weeklyIntervalMinutes = Int(value) }
            }
        }

        guard case .object(let telegram)? = object["telegram"] else { return }
        if case .bool(let value)? = telegram["enabled"] { settings.telegramEnabled = value }
        settings.telegramUserID = firstIDString(telegram["allowed_user_ids"])
        settings.telegramChatID = firstIDString(telegram["allowed_chat_ids"])
        if case .number(let value)? = telegram["notification_channel_id"] {
            settings.notificationIsChannel = true
            settings.notificationID = String(Int64(value))
        } else if case .number(let value)? = telegram["notification_chat_id"] {
            settings.notificationIsChannel = false
            settings.notificationID = String(Int64(value))
        } else {
            settings.notificationID = ""
        }
    }

    func copyClaudeLoginCommand() {
        let board = NSPasteboard.general
        board.clearContents()
        board.setString(claudeLoginCommand, forType: .string)
        statusText = "Claude giriş komutu panoya kopyalandı: \(claudeLoginCommand)"
    }

    private func parseRunResult(_ value: JSONValue?) {
        guard case .object(let object) = value else { return }
        if case .object(let verification)? = object["usage_window_verification"],
           case .bool(let verified)? = verification["verified"] {
            usageWindowText = verified ? "Resmî reset zamanı doğrulandı" : "5 saatlik tahmin kullanılıyor"
        }
    }

    private func renderResult(arguments: [String], result: CommandEnvelope) -> String {
        let command = arguments.first ?? ""
        guard let data = result.data else { return result.status }
        if command == "logs",
           case .object(let object) = data,
           case .array(let lines)? = object["lines"] {
            return lines.compactMap {
                if case .string(let line) = $0 { return line }
                return nil
            }.joined(separator: "\n")
        }
        if command == "run", case .object(let object) = data {
            let model = (object["selected_model"]).flatMap {
                if case .string(let value) = $0 { return value }
                return nil
            } ?? "auto"
            let note = (object["usage_window_verification"]).flatMap { value -> String? in
                guard case .object(let details) = value else { return nil }
                if case .string(let message)? = details["message"] { return message }
                return nil
            } ?? ""
            return note.isEmpty ? "Çalıştırma başarılı. Model: \(model)." : "Çalıştırma başarılı. Model: \(model).\n\(note)"
        }
        if command == "status", case .object(let object) = data {
            let enabled = boolText(object["enabled"], on: "Açık", off: "Kapalı")
            let background = boolText(object["background_enabled"], on: "Açık", off: "Kapalı")
            let telegram = boolText(object["telegram_enabled"], on: "Açık", off: "Kapalı")
            let nextRun = stringValue(object["next_run"]) ?? "Bilinmiyor"
            return "Otomasyon: \(enabled)\nArka plan: \(background)\nTelegram: \(telegram)\nSonraki çalışma: \(nextRun)"
        }
        if case .string(let value) = data { return value }
        return plainText(data)
    }

    private func stringValue(_ value: JSONValue?) -> String? {
        if case .string(let text) = value { return text }
        return nil
    }

    private func boolText(_ value: JSONValue?, on: String, off: String) -> String {
        if case .bool(let flag) = value {
            return flag ? on : off
        }
        return off
    }

    private func firstIDString(_ value: JSONValue?) -> String {
        guard case .array(let items) = value,
              let first = items.first,
              case .number(let number) = first else {
            return ""
        }
        return String(Int64(number))
    }

    private func plainText(_ value: JSONValue, indent: String = "") -> String {
        switch value {
        case .null:
            return "\(indent)-"
        case .bool(let flag):
            return "\(indent)\(flag ? "true" : "false")"
        case .number(let number):
            return "\(indent)\(number)"
        case .string(let text):
            return "\(indent)\(text)"
        case .array(let items):
            return items.enumerated().map { _, item in
                if case .object = item {
                    return plainText(item, indent: "\(indent)- ")
                }
                return "\(indent)- \(plainText(item))"
            }.joined(separator: "\n")
        case .object(let object):
            return object.keys.sorted().compactMap { key in
                guard let child = object[key] else { return nil }
                switch child {
                case .object, .array:
                    return "\(indent)\(key):\n\(plainText(child, indent: "\(indent)  "))"
                default:
                    return "\(indent)\(key): \(plainText(child))"
                }
            }.joined(separator: "\n")
        }
    }
}
