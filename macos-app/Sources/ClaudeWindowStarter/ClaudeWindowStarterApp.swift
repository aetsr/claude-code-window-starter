import AppKit
import SwiftUI

@main
struct ClaudeWindowStarterApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            ContentView(model: model)
                .frame(width: 560, height: 680)
        } label: {
            Image(nsImage: MenuBarTemplateIcon.image)
                .accessibilityLabel("Claude Window Starter")
        }
        .menuBarExtraStyle(.window)
    }
}

@MainActor
enum MenuBarTemplateIcon {
    static let image: NSImage = {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size, flipped: false) { _ in
            NSColor.black.setStroke()

            let window = NSBezierPath(
                roundedRect: NSRect(x: 1.5, y: 2.0, width: 13.0, height: 12.0),
                xRadius: 2.6,
                yRadius: 2.6
            )
            window.lineWidth = 1.7
            window.stroke()

            let inner = NSBezierPath(
                roundedRect: NSRect(x: 4.0, y: 4.5, width: 8.0, height: 7.0),
                xRadius: 1.4,
                yRadius: 1.4
            )
            inner.lineWidth = 1.2
            inner.stroke()

            let sparkle = NSBezierPath()
            sparkle.move(to: NSPoint(x: 14.8, y: 12.2))
            sparkle.line(to: NSPoint(x: 14.8, y: 17.0))
            sparkle.move(to: NSPoint(x: 12.4, y: 14.6))
            sparkle.line(to: NSPoint(x: 17.2, y: 14.6))
            sparkle.move(to: NSPoint(x: 13.2, y: 13.0))
            sparkle.line(to: NSPoint(x: 16.4, y: 16.2))
            sparkle.move(to: NSPoint(x: 16.4, y: 13.0))
            sparkle.line(to: NSPoint(x: 13.2, y: 16.2))
            sparkle.lineWidth = 1.25
            sparkle.lineCapStyle = .round
            sparkle.stroke()
            return true
        }
        image.isTemplate = true
        image.accessibilityDescription = "Claude Window Starter"
        return image
    }()
}
