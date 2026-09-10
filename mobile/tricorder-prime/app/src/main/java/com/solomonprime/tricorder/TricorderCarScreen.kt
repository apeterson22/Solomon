package com.solomonprime.tricorder

import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.CarColor
import androidx.car.app.model.GridItem
import androidx.car.app.model.GridTemplate
import androidx.car.app.model.ItemList
import androidx.car.app.model.Row
import androidx.car.app.model.Template

/**
 * Android Auto screen — displays a 2×2 grid of core OBD2 metrics.
 *
 * Uses a singleton-style data holder so the phone app's ViewModel can push
 * values without a direct reference. In production, wire this through a
 * shared repository or service binding.
 */
class TricorderCarScreen(carContext: CarContext) : Screen(carContext) {

    override fun onGetTemplate(): Template {
        val data = CarObd2DataHolder

        // If not connected, show a simple message grid
        if (!data.connected) {
            return GridTemplate.Builder()
                .setTitle("TRICORDER OBD2")
                .setSingleList(
                    ItemList.Builder()
                        .addItem(
                            GridItem.Builder()
                                .setTitle("NOT CONNECTED")
                                .setText("Start Tricorder app first")
                                .build()
                        )
                        .build()
                )
                .build()
        }

        // 2×2 metric grid
        val gridItems = ItemList.Builder()
            .addItem(
                GridItem.Builder()
                    .setTitle("RPM")
                    .setText("%.0f".format(data.rpm))
                    .build()
            )
            .addItem(
                GridItem.Builder()
                    .setTitle("SPEED")
                    .setText("%.0f km/h".format(data.speed))
                    .build()
            )
            .addItem(
                GridItem.Builder()
                    .setTitle("COOLANT")
                    .setText(buildCoolantText(data.coolantTemp))
                    .build()
            )
            .addItem(
                GridItem.Builder()
                    .setTitle("LOAD")
                    .setText("%.1f%%".format(data.engineLoad))
                    .build()
            )
            .build()

        val actionStrip = ActionStrip.Builder()
            .addAction(
                Action.Builder()
                    .setTitle("MAP")
                    .setOnClickListener {
                        screenManager.push(TricorderCarMapScreen(carContext))
                    }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setTitle("MEDIA")
                    .setOnClickListener {
                        screenManager.push(TricorderCarMediaScreen(carContext))
                    }
                    .build()
            )
            .build()

        val builder = GridTemplate.Builder()
            .setTitle("TRICORDER OBD2")
            .setSingleList(gridItems)
            .setActionStrip(actionStrip)

        // DTC warning row
        if (data.dtcCount > 0) {
            builder.setHeaderAction(
                Action.Builder()
                    .setTitle("⚠ ${data.dtcCount} DTC(s)")
                    .setBackgroundColor(CarColor.RED)
                    .setOnClickListener { /* no-op on Auto, check phone */ }
                    .build()
            )
        }

        return builder.build()
    }

    private fun buildCoolantText(temp: Float): String {
        return if (temp > 110f) {
            "⚠ %.0f°C".format(temp) // over-temp warning
        } else {
            "%.0f°C".format(temp)
        }
    }
}

/**
 * Lightweight data holder shared between the phone-side ViewModel and the
 * Android Auto screen. The ViewModel updates these values; the car screen
 * reads them on each onGetTemplate() call.
 *
 * For production: replace with a proper shared repository / Flow collector.
 */
object CarObd2DataHolder {
    @Volatile var connected: Boolean = false
    @Volatile var rpm: Float = 0f
    @Volatile var speed: Float = 0f
    @Volatile var coolantTemp: Float = 0f
    @Volatile var engineLoad: Float = 0f
    @Volatile var dtcCount: Int = 0
}
