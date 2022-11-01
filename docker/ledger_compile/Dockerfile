from ubuntu:bionic

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y wget bzip2 xz-utils git make libc6-dev-i386 usbutils python3-setuptools zlib1g-dev python3-pip libusb-1.0-0-dev libudev-dev gcc-multilib g++-multilib libjpeg8-dev zlib1g-dev

RUN mkdir /home/bolos_env && cd /home/bolos_env && \
    wget https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu-rm/10-2020q4/gcc-arm-none-eabi-10-2020-q4-major-x86_64-linux.tar.bz2 && \
    tar xvf gcc-arm-none-eabi-10-2020-q4-major-x86_64-linux.tar.bz2

RUN cd /home/bolos_env && \
    wget https://releases.llvm.org/9.0.0/clang+llvm-9.0.0-x86_64-linux-gnu-ubuntu-18.04.tar.xz && \
    tar xvf clang+llvm-9.0.0-x86_64-linux-gnu-ubuntu-18.04.tar.xz && \
    ln -s clang+llvm-9.0.0-x86_64-linux-gnu-ubuntu-18.04 clang-arm-fropi


RUN cd /home && \
    git clone https://github.com/LedgerHQ/nanos-secure-sdk.git && \
    cd /home/nanos-secure-sdk && \
    git checkout 2.0.0-1


ENV LIBPATH="${LIBPATH}:/usr/lib/x86_64-linux-gnu/" \
    BOLOS_SDK=/home/nanos-secure-sdk \
    COIN=particl_testnet

# COIN=particl Or COIN=particl_testnet

RUN ln -s /usr/bin/python3 /usr/bin/python && \
    cd /home && \
    git clone https://github.com/ledgerhq/blue-loader-python && \
    cd /home/blue-loader-python && \
    pip3 install pillow==3.4.0 && \
    pip3 install Cython && \
    pip3 install websocket_client python-u2flib-host ecpy future pycryptodomex protobuf && \
    python3 setup.py install

RUN cd /home && \
    git clone https://github.com/tecnovert/ledger-app-particl.git ledger-app-particl_tv
