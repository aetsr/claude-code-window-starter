import Foundation
import Security

enum KeychainStore {
    static func save(_ value: String, account: String) throws {
        let service = "com.claude-window-starter"
        // Delete any existing item first.
        let deleteQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(deleteQuery as CFDictionary)

        // Build a permissive SecAccess so that any process running as the
        // current user can read the item — even after the app bundle is
        // re-signed by the installer.  This is the programmatic equivalent
        // of `security add-generic-password -T ""`.
        var access: SecAccess?
        let accessStatus = SecAccessCreate(service as CFString, [] as CFArray, &access)
        guard accessStatus == errSecSuccess, let access else {
            throw ProcessRunnerError.launch("Keychain access policy creation failed")
        }

        var item = deleteQuery
        item[kSecValueData as String] = Data(value.utf8)
        item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        item[kSecAttrAccess as String] = access
        let status = SecItemAdd(item as CFDictionary, nil)
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
