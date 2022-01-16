#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""
# for particl-cli

export PARTICL_BINDIR=/tmp/partbuild22/src;
export PARTICL_BINDIR_22=/tmp/partbuild22/src;
export PARTICL_BINDIR_21=~/tmp/particl-0.21.2.6/bin;
export PARTICL_BINDIR_1919=/tmp/partbuild19/src;
export PARTICL_BINDIR_1918=~/tmp/particl-0.19.2.18/bin;
python3 taproot_fork.py


Taproot spending txns should not enter the mempool on 19.18 nodes
All nodes should accept blocks

"""

import os
import sys
import time
import shutil
import signal
import hashlib
import logging
import threading
import traceback
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje, dumpj, b58encode
from util_tests import (
    DATADIRS, startDaemon, callcli,
    stakeBlocks)


from contrib.test_framework.script import taproot_construct
from contrib.test_framework.key import generate_privkey, compute_xonly_pubkey
from contrib.test_framework.segwit_addr import encode_segwit_address


NUM_NODES = 6
BASE_PORT = 14792
BASE_RPC_PORT = 19792
DEBUG_MODE = True
RESET_DATA = True

delay_event = threading.Event()

PARTICL_BINDIR_22 = os.path.expanduser(os.getenv('PARTICL_BINDIR_22', '.'))
PARTICL_BINDIR_21 = os.path.expanduser(os.getenv('PARTICL_BINDIR_21', '.'))
PARTICL_BINDIR_1919 = os.path.expanduser(os.getenv('PARTICL_BINDIR_1919', '.'))
PARTICL_BINDIR_1918 = os.path.expanduser(os.getenv('PARTICL_BINDIR_1918', '.'))


def toWIF(prefix_byte, b, compressed=True):
    b = bytes((prefix_byte,)) + b
    if compressed:
        b += bytes((0x01,))
    b += hashlib.sha256(hashlib.sha256(b).digest()).digest()[:4]
    return b58encode(b)


def signalHandler(sig, frame):
    logging.info('Signal {} detected, ending.'.format(sig))
    delay_event.set()


def prepareDir(datadir, node_id):
    node_dir = os.path.join(datadir, str(node_id))

    if not os.path.exists(node_dir):
        os.makedirs(node_dir)

    config_path = os.path.join(node_dir, 'particl.conf')

    if os.path.exists(config_path):
        return

    rpc_port = BASE_RPC_PORT + node_id
    port = BASE_PORT + node_id

    with open(config_path, 'w+') as fp:
        fp.write('regtest=1\n')
        fp.write('[regtest]\n')

        fp.write('port=' + str(port) + '\n')
        fp.write('rpcport=' + str(rpc_port) + '\n')
        salt = generate_salt(16)
        fp.write('rpcauth={}:{}${}\n'.format('test', salt, password_to_hmac(salt, 'test')))

        fp.write('daemon=1\n')
        fp.write('server=1\n')
        fp.write('discover=0\n')
        fp.write('listenonion=0\n')
        fp.write('bind=127.0.0.1\n')
        fp.write('findpeers=0\n')
        fp.write('debugdevice=0\n')

        if DEBUG_MODE:
            fp.write('debug=1\n')
        fp.write('debugexclude=libevent\n')
        fp.write('displaylocaltime=1\n')
        fp.write('acceptnonstdtxn=0\n')
        fp.write('minstakeinterval=1\n')

        for i in range(0, NUM_NODES):
            if node_id == i:
                continue
            fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))

        fp.write('checkblockindex=0\n')
        fp.write('reservebalance=1000000\n')
        fp.write('txindex=1\n')


def waitForMempool(node, txid, nTries=10):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForMempool stopped.')
        try:
            ro = callcli(node, 'getmempoolentry {}'.format(txid))
        except Exception:
            continue
        return True
    raise ValueError('waitForMempool timed out.')


def doTest():
    global NUM_NODES

    addr_sx0 = callcli(0, 'getnewstealthaddress')

    secret_key = generate_privkey()
    internal_key = compute_xonly_pubkey(secret_key)[0]

    tri = taproot_construct(internal_key)
    scriptPubKey = tri.scriptPubKey

    addr_sw_tr = encode_segwit_address("rtpw", 1, scriptPubKey[2:])
    print('addr_sw_tr', addr_sw_tr)

    outputs = [{'address': addr_sw_tr, 'amount': 1}, ]
    txid = callcli(0, 'sendtypeto part part "{}"'.format(dumpje(outputs)))
    print('txid', txid)

    rv = callcli(1, 'getmempoolinfo')
    print('rv 1', dumpj(rv))

    print('Waiting 8 seconds...')
    time.sleep(8)

    for i in range(0, NUM_NODES):
        rv = callcli(i, 'getmempoolinfo')
        print('getmempoolinfo', i, dumpj(rv))
        assert(rv['size'] == 1)
        rv = callcli(i, 'getrawtransaction {}'.format(txid))
        print('getrawtransaction', i, dumpj(rv))

    rv = callcli(i, 'getrawtransaction {} true'.format(txid))

    vout = -1
    for txo in rv['vout']:
        if txo['scriptPubKey']['address'].startswith('rtpw1'):
            vout = txo['n']
    assert(vout > -1)

    inputs = [{'txid': txid, 'vout': vout}]
    outputs = {addr_sx0: 0.99}

    tx = callcli(0, 'createrawtransaction "{}" "{}"'.format(dumpje(inputs), dumpje(outputs)))
    print('createrawtransaction', dumpj(tx))

    options = {'taproot': {'0': {'output_pubkey': tri.output_pubkey.hex()}}}
    print('signrawtransactionwithkey "{}" "{}" [] DEFAULT "{}"'.format(tx, dumpje([toWIF(0x2e, secret_key), ]), dumpje(options)))
    tx = callcli(0, 'signrawtransactionwithkey "{}" "{}" [] DEFAULT "{}"'.format(tx, dumpje([toWIF(0x2e, secret_key), ]), dumpje(options)))
    print('tx', dumpj(tx))

    spending_txid = callcli(0, 'sendrawtransaction "{}"'.format(tx['hex']))
    print('spending_txid', spending_txid)

    print('Waiting 8 seconds...')
    time.sleep(8)

    for i in range(0, NUM_NODES):
        rv = callcli(i, 'getmempoolinfo')
        print('getmempoolinfo', i, dumpj(rv))
        if i == 3:
            assert(rv['size'] == 1)
        else:
            assert(rv['size'] == 2)

        if i == 3:
            try:
                rv = callcli(i, 'getrawtransaction {}'.format(spending_txid))
            except Exception as e:
                assert('No such mempool or blockchain transaction' in str(e))
        else:
            rv = callcli(i, 'getrawtransaction {}'.format(spending_txid))
            print('getrawtransaction', i, dumpj(rv))

    stakeBlocks(0, 1, delay_event)

    for i in range(0, NUM_NODES):
        rv = callcli(i, 'getmempoolinfo')
        assert(rv['size'] == 0)

        rv = callcli(i, 'getrawtransaction {}'.format(spending_txid))
        print('getrawtransaction', i, dumpj(rv))

    logging.info('Test Passed!')


def runTest(resetData):
    logging.info('Installing signal handler, ctrl+c to quit')
    signal.signal(signal.SIGINT, signalHandler)

    if resetData:
        for i in range(NUM_NODES):
            dirname = os.path.join(DATADIRS, str(i))
            if os.path.isdir(dirname):
                logging.info('Removing' + dirname)
                shutil.rmtree(dirname)

    logging.info('\nPrepare the network')

    for i in range(0, NUM_NODES):
        prepareDir(DATADIRS, i)

        if i == 0:
            startDaemon(i, PARTICL_BINDIR_22)
        elif i == 1:
            startDaemon(i, PARTICL_BINDIR_21)
        elif i == 2:
            startDaemon(i, PARTICL_BINDIR_1919)
        elif i == 3:
            startDaemon(i, PARTICL_BINDIR_1918)
        else:
            startDaemon(i, PARTICL_BINDIR_22)

    for i in range(0, NUM_NODES):
        # Wait until all nodes are responding
        num_tries = 10
        k = 0
        for k in range(num_tries):
            try:
                callcli(i, 'getnetworkinfo')
            except Exception as e:
                print('rpc error', str(e))
                delay_event.wait(1)
                continue
            break
        if k >= num_tries - 1:
            raise ValueError('Can\'t contact node ' + str(i))

        try:
            callcli(i, 'getwalletinfo')
        except Exception as e:
            logging.info('Creating wallet for node: {}'.format(i))
            callcli(i, 'createwallet wallet')

        if i < 2:
            callcli(i, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"100\\",\\"stakesplitthreshold\\":200}"')
        callcli(i, 'reservebalance true 1000000')

    callcli(0, 'extkeygenesisimport "abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb"')

    callcli(1, 'extkeyimportmaster "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')

    callcli(2, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')

    try:
        doTest()
    except Exception:
        traceback.print_exc()

    logging.info('Test Complete.')

    delay_event.set()

    logging.info('Stopping nodes.')
    for i in range(0, NUM_NODES):
        callcli(i, 'stop')


def main():
    if not os.path.exists(DATADIRS):
        os.makedirs(DATADIRS)

    with open(os.path.join(DATADIRS, 'test.log'), 'w') as fp:
        logger = logging.getLogger()
        logger.level = logging.DEBUG
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.addHandler(logging.StreamHandler(fp))

        logging.info(os.path.basename(sys.argv[0]) + '\n\n')
        runTest(RESET_DATA)

    print('Done.')


if __name__ == '__main__':
    main()
