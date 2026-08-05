FROM eclipse-temurin:17-jdk-jammy

ARG ANDROID_COMMAND_LINE_TOOLS=13114758
ENV ANDROID_HOME=/opt/android-sdk \
    ANDROID_SDK_ROOT=/opt/android-sdk \
    PATH=/opt/android-sdk/cmdline-tools/latest/bin:/opt/android-sdk/platform-tools:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /opt/android-sdk/cmdline-tools \
    && curl -fsSL "https://dl.google.com/android/repository/commandlinetools-linux-${ANDROID_COMMAND_LINE_TOOLS}_latest.zip" -o /tmp/tools.zip \
    && unzip -q /tmp/tools.zip -d /tmp/android-tools \
    && mv /tmp/android-tools/cmdline-tools /opt/android-sdk/cmdline-tools/latest \
    && rm -rf /tmp/tools.zip /tmp/android-tools \
    && yes | sdkmanager --licenses >/dev/null \
    && sdkmanager "platform-tools" "platforms;android-36" "build-tools;36.0.0" \
    && chmod -R a+rX /opt/android-sdk

WORKDIR /workspace/mobile/android
