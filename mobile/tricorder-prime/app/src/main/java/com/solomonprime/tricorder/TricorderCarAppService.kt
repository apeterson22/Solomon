package com.solomonprime.tricorder

import android.content.Intent
import android.graphics.Rect
import androidx.car.app.AppManager
import androidx.car.app.CarAppService
import androidx.car.app.CarContext
import androidx.car.app.SurfaceCallback
import androidx.car.app.SurfaceContainer
import androidx.car.app.validation.HostValidator
import androidx.car.app.Session
import androidx.car.app.Screen

class TricorderCarAppService : CarAppService() {
    override fun createHostValidator() = HostValidator.ALLOW_ALL_HOSTS_VALIDATOR
    override fun onCreateSession() = TricorderCarSession()
}

class TricorderCarSession : Session() {

    private var mapScreen: TricorderCarMapScreen? = null

    override fun onCreateScreen(intent: Intent): Screen {
        val screen = TricorderCarScreen(carContext)

        // Register surface callback for pixel map rendering (Car API level >= 2)
        try {
            if (carContext.carAppApiLevel >= 2) {
                val ms = TricorderCarMapScreen(carContext)
                mapScreen = ms
                carContext.getCarService(AppManager::class.java)
                    .setSurfaceCallback(object : SurfaceCallback {
                        override fun onSurfaceAvailable(container: SurfaceContainer) {
                            ms.surfaceCallback.onSurfaceAvailable(container)
                        }

                        override fun onSurfaceDestroyed(container: SurfaceContainer) {
                            ms.surfaceCallback.onSurfaceDestroyed(container)
                        }

                        override fun onVisibleAreaChanged(visibleArea: Rect) {
                            ms.surfaceCallback.onVisibleAreaChanged(visibleArea)
                        }

                        override fun onStableAreaChanged(stableArea: Rect) {
                            ms.surfaceCallback.onStableAreaChanged(stableArea)
                        }
                    })
            }
        } catch (_: Exception) {
            // Surface not supported on this host — gracefully degrade
        }

        return screen
    }
}
