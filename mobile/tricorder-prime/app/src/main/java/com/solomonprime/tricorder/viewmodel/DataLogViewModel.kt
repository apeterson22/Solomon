package com.solomonprime.tricorder.viewmodel

import android.app.Application
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.solomonprime.tricorder.data.DataLogRepository
import com.solomonprime.tricorder.model.ScanSession
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * ViewModel for managing Tricorder data logging operations.
 */
class DataLogViewModel(application: Application) : AndroidViewModel(application) {

    private val repository = DataLogRepository(application.applicationContext)

    private val _sessions = MutableStateFlow<List<ScanSession>>(emptyList())
    val sessions: StateFlow<List<ScanSession>> = _sessions.asStateFlow()

    init {
        loadSessions()
    }

    /**
     * Loads all stored sessions from the repository.
     */
    fun loadSessions() {
        viewModelScope.launch {
            val loaded = withContext(Dispatchers.IO) {
                repository.getSessions()
            }
            _sessions.value = loaded
        }
    }

    /**
     * Logs a new scan snapshot and refreshes the session list.
     */
    fun logSnapshot(session: ScanSession) {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                repository.saveSession(session)
            }
            loadSessions()
        }
    }

    /**
     * Exports the log to a shareable CSV file and returns the content Uri.
     * Returns null if export fails or no data exists.
     */
    fun exportCsv(): Uri? {
        return repository.exportCsv(getApplication())
    }

    /**
     * Clears all logged sessions.
     */
    fun clearLog() {
        viewModelScope.launch {
            withContext(Dispatchers.IO) {
                repository.clearLog()
            }
            _sessions.value = emptyList()
        }
    }
}
