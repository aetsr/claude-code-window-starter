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
                statusText = result.data?.description ?? result.status
                if arguments.first == "status" { parseStatus(result.data) }
            } catch {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func saveConfiguration() {
        busy = true
        lastError = nil
        let userID = Int64(settings.telegramUserID)
        let chatID = Int64(settings.telegramChatID)
        let notificationID = Int64(settings.notificationID)
        let document: [String: Any] = [
            "schema_version": 2,
            "enabled": settings.enabled,
            "background_enabled": settings.backgroundEnabled,
            "schedule_time": settings.scheduleTime,
            "timezone": settings.timezone,
            "model": settings.model,
            "prompt": settings.prompt,
            "timeout_seconds": settings.timeout,
            "allow_catch_up": settings.catchUp,
            "prevent_duplicate_daily_run": true,
            "telegram": [
                "enabled": settings.telegramEnabled,
                "allowed_user_ids": userID.map { [$0] } ?? [],
                "allowed_chat_ids": chatID.map { [$0] } ?? [],
                "allowed_channel_ids": [],
                "notification_chat_id": settings.notificationIsChannel ? NSNull() : (notificationID.map { $0 as Any } ?? NSNull()),
                "notification_channel_id": settings.notificationIsChannel ? (notificationID.map { $0 as Any } ?? NSNull()) : NSNull(),
                "commands_in_private_chat_only": true,
                "notify_success": true,
                "notify_failure": true,
                "command_cooldown_seconds": 3,
                "confirmation_ttl_seconds": 60,
                "max_prompt_length": 500,
            ],
        ]
        do {
            let data = try JSONSerialization.data(withJSONObject: document)
            try SettingsStore.save(settings)
            Task {
                defer { busy = false }
                do {
                    let result = try await backend.applyConfig(data: data)
                    statusText = result.data?.description ?? "Ayarlar kaydedildi"
                } catch {
                    lastError = error.localizedDescription
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
                statusText = result.data?.description ?? "Telegram bağlantısı başarılı"
            } catch {
                lastError = error.localizedDescription
            }
        }
    }

    func parseStatus(_ value: JSONValue?) {
        guard case .object(let object) = value else { return }
        if case .object(let health)? = object["health"], case .object(let checks)? = health["checks"] {
            if case .object(let background)? = checks["background"] {
                if case .bool(let value)? = background["network_online"] { networkOnline = value }
                if case .bool(let value)? = background["power_assertion"] { powerAssertion = value }
            }
        }
        if case .object? = object["pending_automatic"] { pendingAutomatic = true } else { pendingAutomatic = false }
    }
}
