from ubuntu:focal

RUN apt-get update && \
    apt-get upgrade -y && \
    DEBIAN_FRONTEND="noninteractive" apt-get install -y p7zip-full wget git curl openjdk-8-jdk unzip python2 python3 build-essential

ENV NVM_DIR=/usr/local/nvm
ENV NODE_VERSION=v10.24.1
ENV NODE_PATH=$NVM_DIR/versions/node/$NODE_VERSION/lib/node_modules
ENV ANDROID_HOME=/android_sdk
ENV ANDROID_PLATFORM_TOOLS=$ANDROID_HOME/platform-tools
ENV PATH=$NVM_DIR/versions/node/$NODE_VERSION/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH

# https://stackoverflow.com/questions/25899912/install-nvm-in-docker
RUN mkdir -p $NVM_DIR && \
    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.38.0/install.sh | bash && \
    . $NVM_DIR/nvm.sh && \
    nvm install $NODE_VERSION && \
    nvm use $NODE_VERSION && \
    npm -v

RUN . $NVM_DIR/nvm.sh && \
    npm install -g cordova

RUN mkdir -p $ANDROID_HOME && \
    cd $ANDROID_HOME && \
    wget https://dl.google.com/android/repository/commandlinetools-linux-7302050_latest.zip && \
    7z x commandlinetools-linux-7302050_latest.zip && \
    mv cmdline-tools latest && \
    mkdir -p $ANDROID_HOME/cmdline-tools && \
    mv latest $ANDROID_HOME/cmdline-tools/

RUN yes | sdkmanager --licenses && \
    yes | sdkmanager "platform-tools" "platforms;android-29" "build-tools;29.0.2"


ENV PYTHON=/bin/python2
ENV ANDROID_SDK_ROOT=/android_sdk
ENV PATH="$ANDROID_SDK_ROOT/tools/bin:$PATH"
ENV GRADLE_VERSION=7.0
ENV PATH=$PATH:"/opt/gradle/gradle-7.0/bin/"
RUN wget https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip -P /tmp \
    && unzip -d /opt/gradle /tmp/gradle-*.zip \
    && chmod +775 /opt/gradle \
    && gradle --version \
    && rm -rf /tmp/gradle*

RUN git config --global url."https://".insteadOf git://

VOLUME /copay_src
VOLUME /output

WORKDIR /copay_src


