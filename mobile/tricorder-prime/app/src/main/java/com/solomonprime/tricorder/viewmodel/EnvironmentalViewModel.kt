package com.solomonprime.tricorder.viewmodel

import android.app.Application
import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import androidx.lifecycle.AndroidViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

class EnvironmentalViewModel(application: Application) : AndroidViewModel(application), SensorEventListener {

    private val sensorManager: SensorManager =
        application.getSystemService(Context.SENSOR_SERVICE) as SensorManager

    // Sensors
    private val pressureSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_PRESSURE)
    private val lightSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_LIGHT)
    private val temperatureSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_AMBIENT_TEMPERATURE)
    private val humiditySensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_RELATIVE_HUMIDITY)
    private val proximitySensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_PROXIMITY)

    // State flows for sensor data
    private val _pressure = MutableStateFlow<Float?>(null)
    val pressure = _pressure.asStateFlow()

    private val _illuminance = MutableStateFlow<Float?>(null)
    val illuminance = _illuminance.asStateFlow()

    private val _temperature = MutableStateFlow<Float?>(null)
    val temperature = _temperature.asStateFlow()

    private val _humidity = MutableStateFlow<Float?>(null)
    val humidity = _humidity.asStateFlow()

    private val _proximity = MutableStateFlow<Float?>(null)
    val proximity = _proximity.asStateFlow()

    // Sensor availability flags
    private val _hasPressureSensor = MutableStateFlow(false)
    val hasPressureSensor = _hasPressureSensor.asStateFlow()

    private val _hasLightSensor = MutableStateFlow(false)
    val hasLightSensor = _hasLightSensor.asStateFlow()

    private val _hasTemperatureSensor = MutableStateFlow(false)
    val hasTemperatureSensor = _hasTemperatureSensor.asStateFlow()

    private val _hasHumiditySensor = MutableStateFlow(false)
    val hasHumiditySensor = _hasHumiditySensor.asStateFlow()

    private val _hasProximitySensor = MutableStateFlow(false)
    val hasProximitySensor = _hasProximitySensor.asStateFlow()

    init {
        // Register pressure sensor
        pressureSensor?.also { sensor ->
            _hasPressureSensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
        
        // Register light sensor
        lightSensor?.also { sensor ->
            _hasLightSensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
        
        // Register temperature sensor (rare on most devices)
        temperatureSensor?.also { sensor ->
            _hasTemperatureSensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
        
        // Register humidity sensor (rare on most devices)
        humiditySensor?.also { sensor ->
            _hasHumiditySensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
        
        // Register proximity sensor
        proximitySensor?.also { sensor ->
            _hasProximitySensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_NORMAL)
        }
    }

    override fun onSensorChanged(event: SensorEvent?) {
        when (event?.sensor?.type) {
            Sensor.TYPE_PRESSURE -> _pressure.value = event.values[0]
            Sensor.TYPE_LIGHT -> _illuminance.value = event.values[0]
            Sensor.TYPE_AMBIENT_TEMPERATURE -> _temperature.value = event.values[0]
            Sensor.TYPE_RELATIVE_HUMIDITY -> _humidity.value = event.values[0]
            Sensor.TYPE_PROXIMITY -> _proximity.value = event.values[0]
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Not needed for this implementation
    }

    override fun onCleared() {
        super.onCleared()
        sensorManager.unregisterListener(this)
    }
}
