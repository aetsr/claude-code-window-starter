// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "ClaudeWindowStarter",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "ClaudeWindowStarter", targets: ["ClaudeWindowStarter"])
    ],
    targets: [
        .executableTarget(name: "ClaudeWindowStarter"),
        .testTarget(name: "ClaudeWindowStarterTests", dependencies: ["ClaudeWindowStarter"])
    ]
)
