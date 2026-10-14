package com.generated.uap.universal_uap_client

import android.content.Intent
import android.net.Uri
import android.speech.tts.TextToSpeech
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream
import java.io.BufferedInputStream
import java.util.Locale

class MainActivity : FlutterActivity() {
    private val channel = "uap/model_picker"
    private val ttsChannel = "uap/text_to_speech"
    private var pendingResult: MethodChannel.Result? = null
    private var textToSpeech: TextToSpeech? = null
    private var ttsReady = false

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "chooseModel" -> {
                        pendingResult = result
                        startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                            type = "application/octet-stream"
                            addCategory(Intent.CATEGORY_OPENABLE)
                        }, 42)
                    }
                    "copyBundledModel" -> {
                        try {
                            result.success(copyBundledModel())
                        } catch (error: Exception) {
                            result.error("BUNDLED_MODEL_COPY_FAILED", error.message, null)
                        }
                    }
                    else -> result.notImplemented()
                }
            }
        textToSpeech = TextToSpeech(this) { status ->
            ttsReady = status == TextToSpeech.SUCCESS
            if (ttsReady) {
                val spanish = textToSpeech?.setLanguage(Locale("es", "ES"))
                if (spanish == TextToSpeech.LANG_MISSING_DATA || spanish == TextToSpeech.LANG_NOT_SUPPORTED) {
                    val fallback = textToSpeech?.setLanguage(Locale("es"))
                    ttsReady = fallback != TextToSpeech.LANG_MISSING_DATA && fallback != TextToSpeech.LANG_NOT_SUPPORTED
                }
            }
        }
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, ttsChannel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "speak" -> {
                        val text = call.argument<String>("text")?.trim()
                        if (!ttsReady || text.isNullOrEmpty()) {
                            result.error("TTS_UNAVAILABLE", "No hay una voz española disponible en el dispositivo.", null)
                        } else {
                            textToSpeech?.speak(text, TextToSpeech.QUEUE_FLUSH, null, "uap-response")
                            result.success(null)
                        }
                    }
                    "stop" -> { textToSpeech?.stop(); result.success(null) }
                    "dispose" -> { textToSpeech?.stop(); textToSpeech?.shutdown(); ttsReady = false; result.success(null) }
                    else -> result.notImplemented()
                }
            }
    }

    override fun onDestroy() {
        textToSpeech?.stop()
        textToSpeech?.shutdown()
        textToSpeech = null
        super.onDestroy()
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 42) return
        val result = pendingResult ?: return
        pendingResult = null
        if (resultCode != RESULT_OK || data?.data == null) {
            result.success(null)
            return
        }
        try {
            result.success(copyModel(data.data!!))
        } catch (error: Exception) {
            result.error("MODEL_COPY_FAILED", error.message, null)
        }
    }

    private fun copyModel(uri: Uri): String {
        val name = (contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val index = cursor.getColumnIndex("_display_name")
            if (index >= 0 && cursor.moveToFirst()) cursor.getString(index) else null
        } ?: "model.gguf").trim()
        require(name.lowercase(Locale.ROOT).endsWith(".gguf")) {
            "Only .gguf model files are supported."
        }
        val safeName = name.replace(Regex("[^A-Za-z0-9._-]"), "_")
        val targetDir = File(filesDir, "local-models").apply { mkdirs() }
        val target = File(targetDir, safeName)
        contentResolver.openAssetFileDescriptor(uri, "r")?.use { descriptor ->
            require(descriptor.length <= 8L * 1024 * 1024 * 1024) {
                "The model exceeds the 8 GB limit."
            }
        }
        contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "The selected document cannot be opened." }
            FileOutputStream(target).use { output -> input.copyTo(output) }
        }
        require(target.length() > 0) { "The selected model is empty." }
        require(target.length() <= 8L * 1024 * 1024 * 1024) {
            "The model exceeds the 8 GB limit."
        }
        return target.absolutePath
    }

    private fun copyBundledModel(): String {
        val targetDir = File(filesDir, "local-models").apply { mkdirs() }
        val target = File(targetDir, "assistant.gguf")
        val temp = File(targetDir, "assistant.gguf.tmp")
        assets.open("flutter_assets/assets/models/assistant.gguf").use { rawInput ->
            BufferedInputStream(rawInput).use { input ->
                FileOutputStream(temp).use { output ->
                    var total = 0L
                    val buffer = ByteArray(1024 * 1024)
                    var read = input.read(buffer)
                    while (read >= 0) {
                        total += read
                        require(total <= 8L * 1024 * 1024 * 1024) { "The bundled model exceeds the 8 GB limit." }
                        output.write(buffer, 0, read)
                        read = input.read(buffer)
                    }
                }
            }
        }
        require(temp.length() > 0) { "The bundled model is empty." }
        if (target.exists()) require(target.delete()) { "The existing model cannot be replaced." }
        require(temp.renameTo(target)) { "The bundled model cannot be installed atomically." }
        return target.absolutePath
    }
}
