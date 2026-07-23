import Foundation

@main
struct ClaudeWindowStarterAgentMain {
    static func main() async {
        let arguments = Array(CommandLine.arguments.dropFirst())
        let mode = arguments.first ?? "background"
        let command = arguments.dropFirst()
        let agent = BackgroundAgent(mode: mode, command: Array(command))
        await agent.run()
    }
}
