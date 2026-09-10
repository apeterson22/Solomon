package com.solomonprime.tricorder.data

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import com.solomonprime.tricorder.model.ScanSession
import java.io.BufferedReader
import java.io.File
import java.io.FileReader
import java.io.FileWriter

/**
 * Repository for persisting and retrieving ScanSession data as CSV.
 */
class DataLogRepository(private val context: Context) {

    private val logFileName = "tricorder_log.csv"
    private val logFile: File
        get() = File(context.filesDir, logFileName)

    /**
     * Appends a ScanSession row to the CSV log file.
     * Creates the file with header if it doesn't exist.
     */
    fun saveSession(session: ScanSession) {
        val file = logFile
        val needsHeader = !file.exists() || file.length() == 0L

        FileWriter(file, true).use { writer ->
            if (needsHeader) {
                writer.appendLine(ScanSession.csvHeader())
            }
            writer.appendLine(session.toCsvRow())
        }
    }

    /**
     * Reads all ScanSession entries from the CSV log.
     * Returns an empty list if the file doesn't exist or is empty.
     */
    fun getSessions(): List<ScanSession> {
        val file = logFile
        if (!file.exists()) return emptyList()

        val sessions = mutableListOf<ScanSession>()
        BufferedReader(FileReader(file)).use { reader ->
            var isFirstLine = true
            reader.lineSequence().forEach { line ->
                if (isFirstLine) {
                    isFirstLine = false
                    // Skip header
                    return@forEach
                }
                if (line.isNotBlank()) {
                    ScanSession.fromCsvRow(line)?.let { sessions.add(it) }
                }
            }
        }
        return sessions
    }

    /**
     * Copies the CSV log to a shareable cache location and returns a content Uri.
     * Uses FileProvider for secure sharing.
     * Returns null if the log file doesn't exist.
     */
    fun exportCsv(context: Context): Uri? {
        val sourceFile = logFile
        if (!sourceFile.exists()) return null

        val cacheDir = File(context.cacheDir, "exports")
        if (!cacheDir.exists()) {
            cacheDir.mkdirs()
        }

        val exportFile = File(cacheDir, "tricorder_export_${System.currentTimeMillis()}.csv")
        sourceFile.copyTo(exportFile, overwrite = true)

        return FileProvider.getUriForFile(
            context,
            "${context.packageName}.fileprovider",
            exportFile
        )
    }

    /**
     * Deletes the CSV log file.
     */
    fun clearLog() {
        val file = logFile
        if (file.exists()) {
            file.delete()
        }
    }
}
