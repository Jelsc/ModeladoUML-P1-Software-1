package com.generated.uap.universal_uap_client

import android.content.Intent
import android.Manifest
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Bundle
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.io.FileOutputStream
import java.io.BufferedInputStream
import java.util.Locale

class MainActivity : FlutterActivity() {
    private val channel = "uap/model_picker"
    private val voiceChannel = "uap/offline_voice"
    private var pendingResult: MethodChannel.Result? = null
    private var pendingVoiceResult: MethodChannel.Result? = null
    private var recognizer: SpeechRecognizer? = null

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
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, voiceChannel)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "isAvailable" -> result.success(SpeechRecognizer.isRecognitionAvailable(this))
                    "listenOnce" -> listenOnce(result)
                    else -> result.notImplemented()
                }
            }
    }

    private fun listenOnce(result: MethodChannel.Result) {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            result.error("VOICE_UNAVAILABLE", "No Android speech service is installed. You can keep using text input.", null)
            return
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            pendingVoiceResult = result
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 43)
            return
        }
        startRecognition(result)
    }

    private fun startRecognition(result: MethodChannel.Result) {
        pendingVoiceResult = result
        recognizer?.destroy()
        recognizer = SpeechRecognizer.createSpeechRecognizer(this).also { speech ->
            speech.setRecognitionListener(object : RecognitionListener {
                override fun onReadyForSpeech(params: Bundle?) = Unit
                override fun onBeginningOfSpeech() = Unit
                override fun onRmsChanged(rmsdB: Float) = Unit
                override fun onBufferReceived(buffer: ByteArray?) = Unit
                override fun onEndOfSpeech() = Unit
                override fun onPartialResults(partialResults: Bundle?) = Unit
                override fun onEvent(eventType: Int, params: Bundle?) = Unit
                override fun onError(error: Int) {
                    finishVoiceError("Speech recognition failed (code $error). Check the Android speech service and try again.")
                }
                override fun onResults(results: Bundle?) {
                    val values = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)
                    val transcript = values?.firstOrNull()?.trim()
                    if (transcript.isNullOrEmpty()) finishVoiceError("No speech was recognized. You can type the request instead.")
                    else finishVoice(transcript)
                }
            })
            speech.startListening(Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH).apply {
                putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-ES")
                putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
                putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
                putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, false)
            })
        }
    }

    private fun finishVoice(value: String) {
        pendingVoiceResult?.success(value)
        pendingVoiceResult = null
        recognizer?.destroy()
        recognizer = null
    }

    private fun finishVoiceError(message: String) {
        pendingVoiceResult?.error("VOICE_ERROR", message, null)
        pendingVoiceResult = null
        recognizer?.destroy()
        recognizer = null
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != 43) return
        val result = pendingVoiceResult ?: return
        if (grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) startRecognition(result)
        else finishVoiceError("Microphone permission was denied. You can keep using text input.")
    }

    override fun onDestroy() {
        recognizer?.destroy()
        recognizer = null
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
