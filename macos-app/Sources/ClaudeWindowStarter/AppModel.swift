import Foundation
import SwiftUI

@MainActor
final class AppModel: ObservableObject {
    @Published var settings: ClientSettings
    @Published var statusText = "Not checked"
    @Published var busy = false
    @Published var lastError: String?
    @Published var telegramToken = ""
    @Published var oauthToken = ""
    @Published var observedFingerprint = "Not scanned"
    @Published var githubFingerprint = ""
    private var scannedHostKey: ScannedHostKey?

    private let backend = BackendClient()

    init(settings: ClientSettings = SettingsStore.load()) {
        self.settings = settings
    }

    var statusIcon: String { lastError == nil ? (busy ? "clock" : "sparkles") : "exclamationmark.triangle" }

    func perform(_ arguments: [String]) {
        busy = true
        lastError = nil
        Task {
            defer { busy = false }
            do {
                let result = try await backend.command(settings: settings, arguments: arguments)
                statusText = result.data?.description ?? result.status
            } catch {
                lastError = error.localizedDescription
                statusText = error.localizedDescription
            }
        }
    }

    func saveConfiguration() {
        busy = true
        let telegramUser = Int64(settings.telegramUserID)
        let telegramChat = Int64(settings.telegramChatID)
        let notification = Int64(settings.notificationID)
        let document: [String: Any] = [
            "enabled": settings.enabled,
            "schedule_time": settings.scheduleTime,
            "timezone": settings.timezone,
            "model": settings.model,
            "prompt": settings.prompt,
            "timeout_seconds": settings.timeout,
            "allow_catch_up": settings.catchUp,
            "telegram": [
                "enabled": settings.telegramEnabled,
                "allowed_user_ids": telegramUser.map { [$0] } ?? [],
                "allowed_chat_ids": telegramChat.map { [$0] } ?? [],
                "notification_chat_id": settings.notificationIsChannel ? NSNull() : (notification.map { $0 as Any } ?? NSNull()),
                "notification_channel_id": settings.notificationIsChannel ? (notification.map { $0 as Any } ?? NSNull()) : NSNull()
            ],
            "deployment": [
                "repository_url": settings.repositoryURL,
                "branch": settings.branch,
                "retain_releases": settings.retainReleases,
                "auto_update_enabled": settings.autoUpdate,
                "auto_apply_updates": settings.autoApplyUpdates,
                "protected_branch_confirmed": settings.protectedBranchConfirmed
            ]
        ]
        let encoded: Data
        do {
            encoded = try JSONSerialization.data(withJSONObject: document)
            try SettingsStore.save(settings)
        } catch {
            busy = false
            lastError = "Settings could not be saved."
            return
        }
        Task {
            defer { busy = false }
            do {
                let result = try await backend.applyConfig(settings: settings, data: encoded)
                statusText = result.data?.description ?? "Configuration saved"
            } catch {
                lastError = error.localizedDescription
            }
        }
    }

    func transferCredential(name: String, value: String) {
        guard !value.isEmpty else {
            lastError = "Enter a credential."
            return
        }
        busy = true
        Task {
            defer { busy = false }
            do {
                try KeychainStore.save(value, account: name)
                try await backend.storeCredential(settings: settings, name: name, secret: value)
                statusText = "Credential transferred securely; its value will not be displayed."
                if name == "telegram_token" { telegramToken = "" } else { oauthToken = "" }
            } catch {
                lastError = error.localizedDescription
            }
        }
    }

    func testSSH() {
        busy = true
        Task {
            defer { busy = false }
            do { statusText = try await backend.testSSH(settings: settings) }
            catch { lastError = error.localizedDescription }
        }
    }

    func scanHostKey() {
        busy = true
        Task {
            defer { busy = false }
            do {
                let key = try await backend.scanHostKey(settings: settings)
                scannedHostKey = key
                observedFingerprint = key.fingerprint
                statusText = "Compare this fingerprint through the Oracle console before trusting it:\n\(key.fingerprint)"
            } catch { lastError = error.localizedDescription }
        }
    }

    func trustScannedHostKey() {
        guard let scannedHostKey else {
            lastError = "Scan and independently verify the host key first."
            return
        }
        do {
            try backend.trustHostKey(settings: settings, key: scannedHostKey)
            statusText = "Pinned host key saved. A later key change will stop SSH."
        } catch { lastError = error.localizedDescription }
    }

    func configureGitDeployKey() {
        busy = true
        Task {
            defer { busy = false }
            do {
                statusText = try await backend.configureGitDeployKey(
                    settings: settings,
                    expectedFingerprint: githubFingerprint
                )
            } catch { lastError = error.localizedDescription }
        }
    }
}
