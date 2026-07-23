import SwiftUI

@main
struct ClaudeWindowStarterApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra("Claude Window Starter", systemImage: model.statusIcon) {
            ContentView(model: model)
                .frame(width: 560, height: 680)
        }
        .menuBarExtraStyle(.window)
    }
}
