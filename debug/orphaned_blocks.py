#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=/tmp/partbuild/src; python3 orphaned_blocks.py

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
from util_tests import (
    DATADIRS, PARTICL_BINDIR, startDaemon, callcli,
    stakeBlocks, waitForHeight)


NUM_NODES = 2
BASE_PORT = 14792
BASE_RPC_PORT = 19792
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


def waitForPeers(node, num_peers, nTries=10):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForPeers stopped.')
        try:
            ro = callcli(node, 'getpeerinfo'.format())
            if len(ro) >= num_peers:
                return True
        except Exception:
            continue
    raise ValueError('waitForPeers timed out.')


def doTest():

    short_chain_height = 3
    long_chain_height = 4

    bal_0_before = callcli(0, 'getbalances')

    logging.info('Staking {} blocks on node 0'.format(short_chain_height))
    stakeBlocks(0, short_chain_height, delay_event)

    logging.info('Staking {} blocks on node 1'.format(long_chain_height))
    stakeBlocks(1, long_chain_height, delay_event)

    logging.info('Connecting nodes')
    callcli(0, 'addconnection "127.0.0.1:{}" "outbound-full-relay"'.format(BASE_PORT + 1))

    waitForPeers(0, 1)
    waitForPeers(1, 1)

    waitForHeight(0, long_chain_height, delay_event)
    bci_0 = callcli(0, 'getblockchaininfo')
    bci_1 = callcli(1, 'getblockchaininfo')

    print(json.dumps(bci_0, indent=4))
    print(json.dumps(bci_1, indent=4))
    assert(bci_0['bestblockhash'] == bci_1['bestblockhash'])

    bal_0_after = callcli(0, 'getbalances')
    print('bal_0_before', json.dumps(bal_0_before, indent=4))
    print('bal_0_after', json.dumps(bal_0_after, indent=4))
    assert(bal_0_after['mine']['trusted'] == bal_0_before['mine']['trusted'])

    ftx_0 = callcli(0, 'filtertransactions')
    print('ftx_0', json.dumps(ftx_0, indent=4))
    num_orphaned = 0
    for tx in ftx_0:
        if tx['category'] == 'orphaned_stake':
            assert(tx['abandoned'] is True)
            num_orphaned += 1
    assert(num_orphaned == short_chain_height)
    assert(len(ftx_0) == 1 + short_chain_height)

    rv = callcli(0, 'pruneorphanedblocks')
    print('pruneorphanedblocks', json.dumps(rv, indent=4))
    assert(rv['files'][0]['blocks_removed'] == short_chain_height)

    rv = callcli(0, 'pruneorphanedblocks false')
    print('pruneorphanedblocks', json.dumps(rv, indent=4))

    delay_event.wait(5)
    startDaemon(0, PARTICL_BINDIR)
    num_tries = 10
    k = 0
    for k in range(num_tries):
        try:
            callcli(0, 'getnetworkinfo')
        except Exception as e:
            delay_event.wait(1)
            continue
        break
    if k >= num_tries - 1:
        raise ValueError('Can\'t contact node ' + str(0))

    rv = callcli(0, 'pruneorphanedblocks')
    print('pruneorphanedblocks', json.dumps(rv, indent=4))

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
