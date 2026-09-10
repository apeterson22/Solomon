# Tricorder Prime - AI Agent Guidelines

- **Architecture:** Android Jetpack Compose, Kotlin, MVVM.
- **Components:** 
  - `EnvironmentalScanner` (Pressure, Light)
  - `GeophysicalScanner` (Location, Rotation)
  - `EmSpectrumScanner` (Wifi, Bluetooth, Magnetic Field)
- **UI System:** LCARS interface matching the Star Trek aesthetic (Orange, Blue, Pink, Tan).
- **Navigation:** Compose Navigation with single-top back stack behavior.
- **Sensors:** We use `SensorManager` and platform managers. Make sure to declare permissions in `AndroidManifest.xml`.
