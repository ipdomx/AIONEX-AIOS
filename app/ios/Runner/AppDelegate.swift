import Flutter
import MachO
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    if let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "AionexSecurity") {
      AionexSecurity.register(messenger: registrar.messenger())
    }
  }
}

/// Answers the "net.vipe.aionex/security" channel (see MainActivity.kt for Android).
///  - setSecure: iOS cannot block screenshots; the Flutter side hides sensitive
///    screens in the app switcher and while the screen is being recorded.
///  - integrity: local signals of a jailbroken device. Signals only: the server
///    stays the authority.
enum AionexSecurity {
  static func register(messenger: FlutterBinaryMessenger) {
    let channel = FlutterMethodChannel(name: "net.vipe.aionex/security", binaryMessenger: messenger)
    channel.setMethodCallHandler { call, result in
      switch call.method {
      case "setSecure":
        result(nil)
      case "integrity":
        result(integritySignals())
      case "isCaptured":
        result(UIScreen.main.isCaptured)
      default:
        result(FlutterMethodNotImplemented)
      }
    }
  }

  private static let jailbreakPaths = [
    "/Applications/Cydia.app", "/Applications/Sileo.app", "/var/jb",
    "/Library/MobileSubstrate/MobileSubstrate.dylib", "/bin/bash", "/usr/sbin/sshd",
    "/etc/apt", "/private/var/lib/apt/", "/usr/bin/ssh",
  ]

  private static func integritySignals() -> [String: Any] {
    var signals: [String] = []
    #if targetEnvironment(simulator)
    let simulator = true
    #else
    let simulator = false
    if jailbreakPaths.contains(where: { FileManager.default.fileExists(atPath: $0) }) {
      signals.append("jailbreak_files")
    }
    if canWriteOutsideSandbox() {
      signals.append("sandbox_escape")
    }
    if hookingLibraryLoaded() {
      signals.append("hooking_framework")
    }
    #endif
    return [
      "platform": "ios",
      "compromised": !signals.isEmpty,
      "emulator": simulator,
      "debugBuild": isDebugBuild,
      "signals": signals,
    ]
  }

  private static var isDebugBuild: Bool {
    #if DEBUG
    return true
    #else
    return false
    #endif
  }

  private static func canWriteOutsideSandbox() -> Bool {
    let path = "/private/aionex_jb_probe.txt"
    do {
      try "probe".write(toFile: path, atomically: true, encoding: .utf8)
      try? FileManager.default.removeItem(atPath: path)
      return true
    } catch {
      return false
    }
  }

  private static func hookingLibraryLoaded() -> Bool {
    let markers = ["frida", "substrate", "substitute", "libhooker", "cycript"]
    for index in 0..<_dyld_image_count() {
      guard let name = _dyld_get_image_name(index) else { continue }
      let image = String(cString: name).lowercased()
      if markers.contains(where: { image.contains($0) }) { return true }
    }
    return false
  }
}
