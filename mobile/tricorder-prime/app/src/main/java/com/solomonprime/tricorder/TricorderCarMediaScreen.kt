package com.solomonprime.tricorder

import android.content.ComponentName
import android.graphics.Bitmap
import android.media.MediaMetadata
import android.media.session.MediaController
import android.media.session.MediaSessionManager
import android.media.session.PlaybackState
import android.media.AudioManager
import android.os.Build
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.*
import androidx.core.graphics.drawable.IconCompat

/**
 * Android Auto media info screen — shows currently playing track from
 * Spotify, YouTube Music, or any active MediaSession. LCARS-styled
 * list layout with track info rows.
 */
class TricorderCarMediaScreen(carContext: CarContext) : Screen(carContext) {

    override fun onGetTemplate(): Template {
        val mediaInfo = getActiveMediaInfo()

        if (mediaInfo == null) {
            return MessageTemplate.Builder("NO MEDIA PLAYING")
                .setTitle("TRICORDER MEDIA")
                .addAction(
                    Action.Builder()
                        .setTitle("BACK")
                        .setOnClickListener { screenManager.pop() }
                        .build()
                )
                .build()
        }

        // Build LCARS-styled list with track info rows
        val listBuilder = ItemList.Builder()

        // Source row
        listBuilder.addItem(
            Row.Builder()
                .setTitle("SOURCE")
                .addText(mediaInfo.sourceName)
                .build()
        )

        // Track title
        listBuilder.addItem(
            Row.Builder()
                .setTitle("TRACK")
                .addText(mediaInfo.title ?: "Unknown")
                .build()
        )

        // Artist
        listBuilder.addItem(
            Row.Builder()
                .setTitle("ARTIST")
                .addText(mediaInfo.artist ?: "Unknown")
                .build()
        )

        // Album
        if (mediaInfo.album != null) {
            listBuilder.addItem(
                Row.Builder()
                    .setTitle("ALBUM")
                    .addText(mediaInfo.album)
                    .build()
            )
        }

        // Playback state
        listBuilder.addItem(
            Row.Builder()
                .setTitle("STATUS")
                .addText(mediaInfo.playbackStateText)
                .build()
        )

        // Audio sample rate
        val audioManager = carContext.getSystemService(CarContext.AUDIO_SERVICE) as? AudioManager
        val sampleRate = audioManager?.getProperty(AudioManager.PROPERTY_OUTPUT_SAMPLE_RATE)
        if (sampleRate != null) {
            listBuilder.addItem(
                Row.Builder()
                    .setTitle("SAMPLE RATE")
                    .addText("$sampleRate Hz")
                    .build()
            )
        }

        val templateBuilder = ListTemplate.Builder()
            .setTitle("TRICORDER MEDIA — ${mediaInfo.sourceName}")
            .setSingleList(listBuilder.build())
            .setHeaderAction(Action.BACK)

        return templateBuilder.build()
    }

    // ── Media session discovery ───────────────────────────────────────

    private data class MediaInfo(
        val title: String?,
        val artist: String?,
        val album: String?,
        val playbackStateText: String,
        val sourceName: String,
        val albumArt: Bitmap?,
        val packageName: String?,
    )

    private fun getActiveMediaInfo(): MediaInfo? {
        val sessionManager = try {
            carContext.getSystemService(CarContext.MEDIA_SESSION_SERVICE) as? MediaSessionManager
        } catch (_: Exception) {
            null
        } ?: return null

        // Need NotificationListenerService for getActiveSessions — use empty component as fallback
        val controllers: List<MediaController> = try {
            sessionManager.getActiveSessions(
                ComponentName(carContext, NotificationListenerStub::class.java)
            )
        } catch (_: SecurityException) {
            // Fallback: try without component (may work on some devices)
            try {
                @Suppress("DEPRECATION")
                sessionManager.getActiveSessions(null)
            } catch (_: Exception) {
                emptyList()
            }
        }

        if (controllers.isEmpty()) return null

        // Prefer playing session; fallback to first
        val controller = controllers.firstOrNull {
            it.playbackState?.state == PlaybackState.STATE_PLAYING
        } ?: controllers.first()

        val metadata = controller.metadata
        val pkgName = controller.packageName

        val sourceName = when (pkgName) {
            "com.spotify.music" -> "♫ SPOTIFY"
            "com.google.android.apps.youtube.music" -> "♫ YOUTUBE MUSIC"
            else -> "♫ ${pkgName?.substringAfterLast('.')?.uppercase() ?: "MEDIA"}"
        }

        val stateText = when (controller.playbackState?.state) {
            PlaybackState.STATE_PLAYING -> "▶ PLAYING"
            PlaybackState.STATE_PAUSED -> "❚❚ PAUSED"
            PlaybackState.STATE_BUFFERING -> "◌ BUFFERING"
            PlaybackState.STATE_STOPPED -> "■ STOPPED"
            else -> "— UNKNOWN"
        }

        return MediaInfo(
            title = metadata?.getString(MediaMetadata.METADATA_KEY_TITLE),
            artist = metadata?.getString(MediaMetadata.METADATA_KEY_ARTIST),
            album = metadata?.getString(MediaMetadata.METADATA_KEY_ALBUM),
            playbackStateText = stateText,
            sourceName = sourceName,
            albumArt = metadata?.getBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART),
            packageName = pkgName,
        )
    }
}

/**
 * Stub NotificationListenerService component name for MediaSessionManager.
 * The actual service must be declared in AndroidManifest.xml and the user
 * must grant notification access for full media session enumeration.
 */
class NotificationListenerStub : android.service.notification.NotificationListenerService()
