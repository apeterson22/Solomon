# Use a base image with a specific Java and Android SDK version
FROM agostiin/android-builder:1.0

# Set the working directory inside the container
WORKDIR /app

# Copy the entire project into the container
COPY . .

# Run the Gradle build
RUN ./gradlew assembleDebug
