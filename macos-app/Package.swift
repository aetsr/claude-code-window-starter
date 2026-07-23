// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ClaudeWindowStarter",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "ClaudeWindowStarter", targets: ["ClaudeWindowStarter"]),
        .executable(name: "ClaudeWindowStarterAgent", targets: ["ClaudeWindowStarterAgent"])
    ],
    targets: [
        .executableTarget(name: "ClaudeWindowStarter"),
        .executableTarget(
            name: "ClaudeWindowStarterAgent",
            linkerSettings: [
                .linkedFramework("IOKit"),
                .linkedFramework("Network"),
                .linkedFramework("Security")
            ]
        ),
        .testTarget(name: "ClaudeWindowStarterTests", dependencies: ["ClaudeWindowStarter"])
    ]
)
