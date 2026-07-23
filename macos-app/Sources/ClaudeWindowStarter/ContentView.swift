import SwiftUI

struct ContentView: View {
    @ObservedObject var model: AppModel

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Picker("Mode", selection: $model.settings.target) {
                    ForEach(ExecutionTarget.allCases) { Text($0.rawValue).tag($0) }
                }
                .pickerStyle(.segmented)
                if model.busy { ProgressView().controlSize(.small) }
            }

            TabView {
                automation.tabItem { Label("Claude", systemImage: "sparkles") }
                oracle.tabItem { Label("Oracle", systemImage: "server.rack") }
                telegram.tabItem { Label("Telegram", systemImage: "paperplane") }
                deployment.tabItem { Label("Git", systemImage: "arrow.triangle.branch") }
            }

            GroupBox("Result") {
                ScrollView {
                    Text(model.statusText)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(height: 130)
            }
            if let error = model.lastError {
                Text(error).foregroundStyle(.red).font(.caption)
            }
            HStack {
                Button("Status") { model.perform(["status"]) }
                Button("Dry-run") { model.perform(["run", "--dry-run", "--trigger", "macos_ui"]) }
                Button("Diagnose") { model.perform(["diagnose"]) }
                Spacer()
                Button("Save") { model.saveConfiguration() }.buttonStyle(.borderedProminent)
            }
        }
        .padding()
        .disabled(model.busy)
    }

    private var automation: some View {
        Form {
            Toggle("Automation enabled", isOn: $model.settings.enabled)
            TextField("Daily time (HH:MM)", text: $model.settings.scheduleTime)
            TextField("IANA timezone", text: $model.settings.timezone)
            Picker("Model", selection: $model.settings.model) {
                ForEach(["auto", "haiku", "sonnet", "opus"], id: \.self, content: Text.init)
            }
            TextField("Prompt", text: $model.settings.prompt, axis: .vertical)
            Stepper("Timeout: \(model.settings.timeout)s", value: $model.settings.timeout, in: 10...1800)
            Toggle("Same-day catch-up", isOn: $model.settings.catchUp)
            HStack {
                Button("Run now") { model.perform(["run", "--manual", "--trigger", "macos_ui"]) }
                Button("Health") { model.perform(["health"]) }
                Button("Version") { model.perform(["version"]) }
            }
            Text("A successful request does not prove that the five-hour usage window started.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding()
    }

    private var oracle: some View {
        Form {
            TextField("Host or IP", text: $model.settings.host)
            TextField("SSH user", text: $model.settings.user)
            TextField("SSH key path", text: $model.settings.keyPath)
            Stepper("SSH port: \(model.settings.port)", value: $model.settings.port, in: 1...65535)
            TextField("Pinned known_hosts file", text: $model.settings.knownHostsPath)
            Text("Observed fingerprint: \(model.observedFingerprint)")
                .font(.caption).textSelection(.enabled)
            HStack {
                Button("Scan host key") { model.scanHostKey() }
                Button("Trust verified key") { model.trustScannedHostKey() }
            }
            Button("Test strict SSH connection") { model.testSSH() }
            SecureField("Claude setup-token", text: $model.oauthToken)
            Button("Transfer OAuth credential") {
                model.transferCredential(name: "claude_oauth_token", value: model.oauthToken)
            }
            Text("The app never uses StrictHostKeyChecking=no and stops if the host key changes.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding()
    }

    private var telegram: some View {
        Form {
            Toggle("Telegram enabled", isOn: $model.settings.telegramEnabled)
            SecureField("BotFather token", text: $model.telegramToken)
            TextField("Allowed user ID", text: $model.settings.telegramUserID)
            TextField("Allowed chat ID", text: $model.settings.telegramChatID)
            TextField("Notification chat/channel ID", text: $model.settings.notificationID)
            Toggle("Notification target is a channel", isOn: $model.settings.notificationIsChannel)
            Button("Transfer Telegram credential") {
                model.transferCredential(name: "telegram_token", value: model.telegramToken)
            }
            Button("Send test message") { model.perform(["telegram-test"]) }
            HStack {
                Button("Start bot") { model.perform(["service", "telegram", "start"]) }
                Button("Stop bot") { model.perform(["service", "telegram", "stop"]) }
                Button("Restart bot") { model.perform(["service", "telegram", "restart"]) }
            }
            Text("Commands are private-chat-only by default; channels receive notifications only.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding()
    }

    private var deployment: some View {
        Form {
            TextField("Private GitHub SSH URL", text: $model.settings.repositoryURL)
            TextField("Protected branch", text: $model.settings.branch)
            Toggle("Protected branch and required checks confirmed", isOn: $model.settings.protectedBranchConfirmed)
            TextField("Verified GitHub ED25519 fingerprint", text: $model.githubFingerprint)
            Button("Generate/configure read-only deploy key") { model.configureGitDeployKey() }
            Stepper("Retain releases: \(model.settings.retainReleases)", value: $model.settings.retainReleases, in: 2...20)
            Toggle("Automatic update checks", isOn: $model.settings.autoUpdate)
            Toggle("Automatically apply updates", isOn: $model.settings.autoApplyUpdates)
                .disabled(!model.settings.autoUpdate)
            HStack {
                Button("Check updates") { model.perform(["update", "--check"]) }
                Button("Apply update") { model.perform(["update", "--apply"]) }
            }
            HStack {
                Button("List releases") { model.perform(["releases"]) }
                Button("Rollback") { model.perform(["rollback", "--yes"]) }
            }
            HStack {
                Button("Fetch logs") { model.perform(["logs", "--lines", "50"]) }
                Button("Restart timer") { model.perform(["service", "timer", "restart"]) }
            }
            Text("The server accepts only the configured origin branch head. CI status relies on protected-main required checks and is not claimed as machine-verified.")
                .font(.caption).foregroundStyle(.secondary)
        }.padding()
    }
}
