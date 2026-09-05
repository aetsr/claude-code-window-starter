import Foundation
import Security

enum KeychainStore {
    static func save(_ value: String, account: String) throws {
        let service = "com.claude-window-starter"
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        // Trust only this app and its bundled supervisor, never an empty
        // (allow-all) application list. Ad-hoc rebuilds may require reapproval.
        guard let executable = Bundle.main.executableURL else {
            throw ProcessRunnerError.launch("Cannot identify the app for Keychain access")
        }
        let helper = Bundle.main.bundleURL.appending(path: "Contents/Helpers/ClaudeWindowStarterAgent")
        var trustedApplications: [SecTrustedApplication] = []
        for path in [executable.path, helper.path] {
            var trusted: SecTrustedApplication?
            let status = SecTrustedApplicationCreateFromPath(path, &trusted)
            guard status == errSecSuccess, let trusted else {
                throw ProcessRunnerError.launch("Cannot authorize the app helper in Keychain")
            }
            trustedApplications.append(trusted)
        }
        var access: SecAccess?
        let accessStatus = SecAccessCreate(service as CFString, trustedApplications as CFArray, &access)
        guard accessStatus == errSecSuccess, let access else {
            throw ProcessRunnerError.launch("Keychain access policy creation failed")
        }

        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccess as String: access,
        ]
        // Preserve an existing token if updating its access policy fails.
        var status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var item = query
            item.merge(attributes) { _, new in new }
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(item as CFDictionary, nil)
        }
        guard status == errSecSuccess else {
            throw ProcessRunnerError.launch("Keychain write failed (\(status))")
        }
    }

    static func load(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.claude-window-starter",
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
}
