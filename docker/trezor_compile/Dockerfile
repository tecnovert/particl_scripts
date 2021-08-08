from ubuntu:focal

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y python-is-python3 python3-pip gcc-arm-none-eabi build-essential curl git libprotobuf-dev protobuf-compiler libusb-1.0-0-dev && \
    curl -sSL https://raw.githubusercontent.com/python-poetry/poetry/master/get-poetry.py | python && \
    pip install poetry

COPY ./particl_trezor-firmware /particl_trezor-firmware

RUN cd /particl_trezor-firmware && \
    cd python && \
    make install && \
    cd /particl_trezor-firmware/legacy && \
    poetry install && \
    poetry run ./script/setup

WORKDIR /particl_trezor-firmware/legacy
