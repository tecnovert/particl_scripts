
Minimal example running two connected BTC nodes in regtest mode:

    export BIN_DIR="$HOME/tmp/bitcoin-23.0/bin"
    mkdir -p /tmp/btc/{1,2}
    alias btcd1="$BIN_DIR/bitcoind --regtest --datadir=/tmp/btc/1"
    alias btcd2="$BIN_DIR/bitcoind --regtest --datadir=/tmp/btc/2"

    printf "[regtest]\nport=%d\nrpcport=%d\n" 10067 10167 > /tmp/btc/1/bitcoin.conf
    printf "[regtest]\nport=%d\nrpcport=%d\n" 10068 10168 > /tmp/btc/2/bitcoin.conf

    btcd1 --daemon
    btcd2 --daemon

    alias btccli1="$BIN_DIR/bitcoin-cli --regtest --datadir=/tmp/btc/1"
    alias btccli2="$BIN_DIR/bitcoin-cli --regtest --datadir=/tmp/btc/2"

    btccli1 addnode 127.0.0.1:10068 add
    btccli1 getnetworkinfo
    # "connections" should be > 0

    btccli1 createwallet test
    export ADDR1=$(btccli1 getnewaddress)
    echo $ADDR1
    bcrt1qzt7e39dztw25023t8jnvnfzvr3lf9qskywe442

    btccli1 generatetoaddress 100 $ADDR1

    btccli2 getblockchaininfo
    # "blocks" should be 100

    btccli1 stop
    btccli2 stop
