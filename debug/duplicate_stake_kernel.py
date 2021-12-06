#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=/tmp/partbuild/src; python3 duplicate_stake_kernel.py

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

    short_chain_height = 5

    bal_0_before = callcli(0, 'getbalances')

    logging.info('Connecting nodes')
    callcli(0, 'addconnection "127.0.0.1:{}" "outbound-full-relay"'.format(BASE_PORT + 1))
    callcli(0, 'addconnection "127.0.0.1:{}" "outbound-full-relay"'.format(BASE_PORT + 2))

    print('exit_ibd 0', callcli(0, 'debugwallet "{\\"exit_ibd\\":true}"'))
    print('exit_ibd 1', callcli(1, 'debugwallet "{\\"exit_ibd\\":true}"'))
    print('exit_ibd 2', callcli(2, 'debugwallet "{\\"exit_ibd\\":true}"'))

    waitForPeers(0, 1)
    waitForPeers(1, 1)

    addr1 = callcli(1, 'getnewaddress')
    tx_kernel = callcli(0, f'sendtoaddress {addr1} 4000')
    tx_kernel1 = callcli(0, f'sendtoaddress {addr1} 4000')

    logging.info('Staking {} blocks on node 0'.format(short_chain_height))
    stakeBlocks(0, short_chain_height, delay_event)

    waitForHeight(1, short_chain_height, delay_event)
    waitForHeight(2, short_chain_height, delay_event)

    rv = callcli(2, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"5000\\",\\"stakesplitthreshold\\":10000}"')
    print('stakingoptions 2', json.dumps(rv, indent=4))
    print('stakingoptions 2', json.dumps(callcli(2, 'walletsettings stakingoptions'), indent=4))

    node0_peers = callcli(0, 'getpeerinfo')
    node1_peers = callcli(1, 'getpeerinfo')
    node2_peers = callcli(2, 'getpeerinfo')
    print('node0_peers', json.dumps(node0_peers, indent=4))
    print('node1_peers', json.dumps(node1_peers, indent=4))
    print('node2_peers', json.dumps(node2_peers, indent=4))

    print('disconnectnode 2', json.dumps(callcli(2, 'disconnectnode "" 0'), indent=4))

    print('node2_peers', json.dumps(node2_peers, indent=4))


    print('wallet info 1', json.dumps(callcli(1, 'getwalletinfo'), indent=4))
    print('wallet info 2', json.dumps(callcli(2, 'getwalletinfo'), indent=4))

    print('staking info 1', json.dumps(callcli(1, 'getstakinginfo'), indent=4))
    print('staking info 2', json.dumps(callcli(2, 'getstakinginfo'), indent=4))

    print('tx_kernel1', tx_kernel1)
    unspents = callcli(1, 'listunspent')
    print('unspents 1', json.dumps(unspents, indent=4))

    print('unspents 1 1', json.dumps(unspents[1], indent=4))
    print('unspents 1 1 txid', unspents[1]['txid'])

    unspent_to_lock = [{'txid': unspents[1]['txid'], 'vout': unspents[1]['vout']}]
    callcli(1, 'lockunspent false "{}"'.format(dumpje(unspent_to_lock)))
    callcli(2, 'lockunspent false "{}"'.format(dumpje(unspent_to_lock)))

    print('getblockchaininfo 1', json.dumps(callcli(1, 'getblockchaininfo'), indent=4))
    print('getblockchaininfo 2', json.dumps(callcli(2, 'getblockchaininfo'), indent=4))

    next_block = short_chain_height + 1
    callcli(1, 'walletsettings stakelimit "{}"'.format(dumpje({'height': next_block})))
    callcli(1, 'reservebalance false')

    callcli(2, 'walletsettings stakelimit "{}"'.format(dumpje({'height': next_block})))
    callcli(2, 'reservebalance false')

    waitForHeight(1, next_block, delay_event)
    waitForHeight(2, next_block, delay_event)

    logging.info('Connecting node 2')
    callcli(0, 'addconnection "127.0.0.1:{}" "outbound-full-relay"'.format(BASE_PORT + 2))
    callcli(1, 'addconnection "127.0.0.1:{}" "outbound-full-relay"'.format(BASE_PORT + 2))

    bci0 = callcli(0, 'getblockchaininfo')
    bci1 = callcli(1, 'getblockchaininfo')
    bci2 = callcli(2, 'getblockchaininfo')
    print('getblockchaininfo 0', json.dumps(bci0, indent=4))
    print('getblockchaininfo 1', json.dumps(bci1, indent=4))
    print('getblockchaininfo 2', json.dumps(bci2, indent=4))

    callcli(1, 'lockunspent true "{}"'.format(dumpje(unspent_to_lock)))
    callcli(2, 'lockunspent true "{}"'.format(dumpje(unspent_to_lock)))

    if bci0['bestblockhash'] == bci1['bestblockhash']:
        stakeBlocks(2, 1, delay_event)
    else:
        stakeBlocks(1, 1, delay_event)

    delay_event.wait(10)

    bci0 = callcli(0, 'getblockchaininfo')
    bci1 = callcli(1, 'getblockchaininfo')
    bci2 = callcli(2, 'getblockchaininfo')
    print('getblockchaininfo 0', json.dumps(bci0, indent=4))
    print('getblockchaininfo 1', json.dumps(bci1, indent=4))
    print('getblockchaininfo 2', json.dumps(bci2, indent=4))

    delay_event.wait(10)

    height = bci0['blocks']
    for i in range(height + 1):
        block_hash = callcli(0, f'getblockhash {i}')
        block = callcli(0, f'getblock {block_hash} 3')
        #print('block', json.dumps(block, indent=4))

        tx0_hash = block['tx'][0]['txid']
        print(f'block {i} {block_hash} {tx0_hash}')

    assert(bci0['bestblockhash'] == bci1['bestblockhash'])
    assert(bci0['bestblockhash'] == bci2['bestblockhash'])

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
    callcli(1, 'extkeygenesisimport "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')
    callcli(2, 'extkeygenesisimport "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')

    #callcli(1, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    #callcli(2, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')

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
