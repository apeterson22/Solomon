package com.solomonprime.tricorder.viewmodel

import android.Manifest
import android.app.Application
import android.content.Context
import android.content.pm.PackageManager
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.os.Looper
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import com.google.android.gms.location.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow

class GeophysicalViewModel(application: Application) : AndroidViewModel(application), SensorEventListener {

    private val sensorManager: SensorManager =
        application.getSystemService(Context.SENSOR_SERVICE) as SensorManager
    
    private val fusedLocationClient: FusedLocationProviderClient =
        LocationServices.getFusedLocationProviderClient(application)

    // Sensors
    private val accelerometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
    private val magnetometer: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_MAGNETIC_FIELD)
    private val gyroscope: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GYROSCOPE)
    private val gravitySensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_GRAVITY)
    private val rotationVectorSensor: Sensor? = sensorManager.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR)

    // State Flows
    private val _location = MutableStateFlow<String>("(Requesting Location...)")
    val location = _location.asStateFlow()

    private val _latitude = MutableStateFlow<Double?>(null)
    val latitude = _latitude.asStateFlow()

    private val _longitude = MutableStateFlow<Double?>(null)
    val longitude = _longitude.asStateFlow()

    private val _altitude = MutableStateFlow<Double?>(null)
    val altitude = _altitude.asStateFlow()

    private val _speed = MutableStateFlow<Float?>(null)
    val speed = _speed.asStateFlow()

    private val _bearing = MutableStateFlow<Float?>(null)
    val bearing = _bearing.asStateFlow()

    private val _heading = MutableStateFlow<Float?>(null)
    val heading = _heading.asStateFlow()

    private val _accelerometerData = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val accelerometerData = _accelerometerData.asStateFlow()

    private val _magnetometerData = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val magnetometerData = _magnetometerData.asStateFlow()

    private val _gyroscopeData = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val gyroscopeData = _gyroscopeData.asStateFlow()

    private val _gravityData = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val gravityData = _gravityData.asStateFlow()

    private val _rotationData = MutableStateFlow(floatArrayOf(0f, 0f, 0f))
    val rotationData = _rotationData.asStateFlow()

    // Sensor availability
    private val _hasGyroscope = MutableStateFlow(false)
    val hasGyroscope = _hasGyroscope.asStateFlow()

    private val _hasGravitySensor = MutableStateFlow(false)
    val hasGravitySensor = _hasGravitySensor.asStateFlow()

    private val _hasRotationVector = MutableStateFlow(false)
    val hasRotationVector = _hasRotationVector.asStateFlow()

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(locationResult: LocationResult) {
            locationResult.lastLocation?.let { loc ->
                _latitude.value = loc.latitude
                _longitude.value = loc.longitude
                _altitude.value = loc.altitude
                _speed.value = if (loc.hasSpeed()) loc.speed else null
                _bearing.value = if (loc.hasBearing()) loc.bearing else null
                _location.value = "Lat: %.6f, Lon: %.6f".format(loc.latitude, loc.longitude)
            }
        }
    }

    init {
        // Register accelerometer
        accelerometer?.also { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
        
        // Register magnetometer
        magnetometer?.also { sensor ->
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
        
        // Register gyroscope
        gyroscope?.also { sensor ->
            _hasGyroscope.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
        
        // Register gravity sensor
        gravitySensor?.also { sensor ->
            _hasGravitySensor.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }
        
        // Register rotation vector sensor
        rotationVectorSensor?.also { sensor ->
            _hasRotationVector.value = true
            sensorManager.registerListener(this, sensor, SensorManager.SENSOR_DELAY_UI)
        }

        // Start location updates
        startLocationUpdates()
    }

    private fun startLocationUpdates() {
        val context = getApplication<Application>().applicationContext
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
            val locationRequest = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 2000)
                .setMinUpdateIntervalMillis(1000)
                .build()
            fusedLocationClient.requestLocationUpdates(locationRequest, locationCallback, Looper.getMainLooper())
        } else {
            _location.value = "(Location Permission Not Granted)"
        }
    }

    override fun onSensorChanged(event: SensorEvent?) {
        when (event?.sensor?.type) {
            Sensor.TYPE_ACCELEROMETER -> {
                _accelerometerData.value = event.values.clone()
                computeHeading()
            }
            Sensor.TYPE_MAGNETIC_FIELD -> {
                _magnetometerData.value = event.values.clone()
                computeHeading()
            }
            Sensor.TYPE_GYROSCOPE -> _gyroscopeData.value = event.values.clone()
            Sensor.TYPE_GRAVITY -> _gravityData.value = event.values.clone()
            Sensor.TYPE_ROTATION_VECTOR -> {
                if (event.values.size >= 3) {
                    _rotationData.value = floatArrayOf(event.values[0], event.values[1], event.values[2])
                }
            }
        }
    }

    private fun computeHeading() {
        val accel = _accelerometerData.value
        val mag = _magnetometerData.value
        val rotationMatrix = FloatArray(9)
        val inclinationMatrix = FloatArray(9)
        if (SensorManager.getRotationMatrix(rotationMatrix, inclinationMatrix, accel, mag)) {
            val orientation = FloatArray(3)
            SensorManager.getOrientation(rotationMatrix, orientation)
            val azimuth = Math.toDegrees(orientation[0].toDouble()).toFloat()
            _heading.value = (azimuth + 360f) % 360f
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {
        // Not needed for this implementation
    }

    override fun onCleared() {
        super.onCleared()
        sensorManager.unregisterListener(this)
        fusedLocationClient.removeLocationUpdates(locationCallback)
    }
}
