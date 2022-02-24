#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""
export PARTICL_BINDIR=~/tmp/particl-0.21.2.7/bin/; python3 encrypted_anon.py
export PARTICL_BINDIR=/tmp/partbuild/src; python3 encrypted_anon.py

"""

import os
import sys
import json
import shutil
import signal
import logging
import threading
import traceback
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje
from util_tests import (
    DATADIRS, PARTICL_BINDIR, startDaemon, callcli,
    stakeBlocks, waitForHeight)


NUM_NODES = 3
BASE_PORT = 14732
BASE_RPC_PORT = 19732
DEBUG_MODE = True
RESET_DATA = True

delay_event = threading.Event()


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

        if DEBUG_MODE:
            fp.write('debug=1\n')
        fp.write('debugexclude=libevent\n')
        fp.write('acceptnonstdtxn=0\n')
        fp.write('minstakeinterval=1\n')
        fp.write('checkpeerheight=0\n')
        fp.write('minstakeinterval=1\n')
        fp.write('stakethreadconddelayms=1000\n')

        for i in range(0, NUM_NODES):
            if node_id == i:
                continue
            fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))


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

    password2 = 'testpwd'
    logging.info('Encrypting wallet 2')
    rv = callcli(2, 'encryptwallet "{}"'.format(password2))
    logging.info('encryptwallet 2: {}'.format(rv))

    callcli(2, 'walletpassphrase "{}" 60'.format(password2))
    sxaddr2 = callcli(2, 'getnewstealthaddress')
    logging.info(callcli(2, 'walletlock'))

    outputs = [{'address': sxaddr2, 'amount': 1.0},]
    txid = callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))

    logging.info('waiting for mempool txid: {}'.format(txid))
    waitForMempool(0, txid)
    logging.info('staking')
    stakeBlocks(0, 1, delay_event)
    waitForHeight(2, 1, delay_event)

    rv = callcli(2, 'filtertransactions')
    logging.info('filtertransactions 2: {}'.format(rv, indent=4))

    callcli(2, 'walletpassphrase "{}" 60'.format(password2))
    logging.info('debugwallet 2: {}'.format(json.dumps(callcli(2, 'debugwallet'), indent=4)))
    logging.info(callcli(2, 'walletlock'))

    rv = callcli(2, 'filtertransactions')
    logging.info('filtertransactions 2: {}'.format(json.dumps(rv, indent=4)))

    callcli(2, 'walletpassphrase "{}" 60'.format(password2))
    logging.info('debugwallet 2: {}'.format(json.dumps(callcli(2, 'debugwallet'), indent=4)))
    logging.info(callcli(2, 'walletlock'))

    txids = []
    sxaddr1 = callcli(1, 'getnewstealthaddress')
    for i in range(20):
        outputs = [{'address': sxaddr1, 'amount': 1.0}]
        txids.append(callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs))))

    callcli(2, 'walletpassphrase "{}" 160'.format(password2))
    outputs = [{'address': sxaddr2, 'amount': 1.0},]
    txids.append(callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs))))

    logging.info('waiting for mempool')
    for txid in txids:
        waitForMempool(0, txid)

    logging.info('staking')
    stakeBlocks(0, 1, delay_event)
    waitForHeight(2, 2, delay_event)

    rv = callcli(2, 'filtertransactions')
    logging.info('filtertransactions 2: {}'.format(json.dumps(rv, indent=4)))
    logging.info('debugwallet 2: {}'.format(json.dumps(callcli(2, 'debugwallet'), indent=4)))

    logging.info('getbalances 2: {}'.format(json.dumps(callcli(2, 'getbalances'), indent=4)))

    while True:
        rv = callcli(2, 'getbalances')
        if rv['mine']['anon_trusted'] >= 2.0:
            break
        logging.info('staking')
        stakeBlocks(0, 1, delay_event)

    outputs = [{'address': sxaddr2, 'amount': 2.0, 'subfee': True},]
    txid = callcli(2, 'sendtypeto anon anon "{}" "" "" 5'.format(dumpje(outputs)))

    logging.info('waiting for mempool txid: {}'.format(txid))
    waitForMempool(0, txid)
    logging.info('staking')
    stakeBlocks(0, 1, delay_event)
    waitForHeight(2, callcli(0, 'getblockcount'), delay_event)

    rv = callcli(2, 'filtertransactions')
    logging.info('filtertransactions 2: {}'.format(json.dumps(rv, indent=4)))
    rv = callcli(2, 'debugwallet')
    logging.info('debugwallet 2: {}'.format(json.dumps(rv, indent=4)))
    assert(len(rv['errors']) == 0)

    logging.info('Test passed!')


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
        startDaemon(i, PARTICL_BINDIR)

    for i in range(0, NUM_NODES):
        # Wait until all nodes are responding
        num_tries = 10
        k = 0
        for k in range(num_tries):
            try:
                callcli(i, 'getnetworkinfo')
            except Exception as e:
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
    callcli(1, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    callcli(2, 'extkeygenesisimport "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')

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
