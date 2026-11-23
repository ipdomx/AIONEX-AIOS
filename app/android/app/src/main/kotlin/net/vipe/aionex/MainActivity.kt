package net.vipe.aionex

import android.content.pm.ApplicationInfo
import android.os.Build
import android.os.Debug
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File

/**
 * Hosts the Flutter app and answers the "net.vipe.aionex/security" channel:
 *  - setSecure(bool): FLAG_SECURE, so sign-in, codes and payments never appear
 *    in screenshots, screen recordings or the recent-apps preview.
 *  - integrity(): local signals of a modified device (root, hooking tools,
 *    emulator, debugger). Signals only: the server stays the authority.
 */
class MainActivity : FlutterActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "setSecure" -> {
                    if (call.arguments == true) {
                        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    } else {
                        window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
                    }
                    result.success(null)
                }
                "integrity" -> result.success(integritySignals())
                else -> result.notImplemented()
            }
        }
    }

    private fun integritySignals(): Map<String, Any> {
        val signals = mutableListOf<String>()
        if (ROOT_PATHS.any { File(it).exists() }) signals.add("su_binary")
        if (Build.TAGS?.contains("test-keys") == true) signals.add("test_keys")
        if (MAGISK_PATHS.any { File(it).exists() }) signals.add("magisk")
        if (hookingLibraryLoaded()) signals.add("hooking_framework")
        val emulator = isEmulator()
        val debuggable = (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        if (Debug.isDebuggerConnected()) signals.add("debugger")
        return mapOf(
            "platform" to "android",
            "compromised" to signals.isNotEmpty(),
            "emulator" to emulator,
            "debugBuild" to debuggable,
            "signals" to signals,
        )
    }

    private fun hookingLibraryLoaded(): Boolean = try {
        File("/proc/self/maps").useLines { lines ->
            lines.any { line -> HOOK_MARKERS.any { line.contains(it, ignoreCase = true) } }
        }
    } catch (_: Exception) {
        false
    }

    private fun isEmulator(): Boolean {
        val fingerprint = Build.FINGERPRINT ?: ""
        val hardware = Build.HARDWARE ?: ""
        return fingerprint.startsWith("generic") || fingerprint.contains("emulator") ||
            hardware.contains("goldfish") || hardware.contains("ranchu") ||
            (Build.MODEL ?: "").contains("sdk_gphone")
    }

    private companion object {
        const val CHANNEL = "net.vipe.aionex/security"
        val ROOT_PATHS = listOf(
            "/system/bin/su", "/system/xbin/su", "/sbin/su", "/system/su",
            "/system/sd/xbin/su", "/data/local/xbin/su", "/data/local/bin/su", "/data/local/su",
            "/su/bin/su", "/system/app/Superuser.apk",
        )
        val MAGISK_PATHS = listOf("/sbin/.magisk", "/data/adb/magisk", "/data/adb/modules", "/cache/.disable_magisk")
        val HOOK_MARKERS = listOf("frida", "xposed", "substrate", "lsposed", "riru", "zygisk")
    }
}
