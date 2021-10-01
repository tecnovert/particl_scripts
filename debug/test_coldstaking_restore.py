#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=~/tmp/particl-0.19.2.13/bin/; python3 test_coldstaking_restore.py
export PARTICL_BINDIR=/tmp/partbuild/src; python3 test_coldstaking_restore.py

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
    waitForDaemonRpc, stakeBlocks, getInternalChain, waitForMempool)


NUM_NODES = 4
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


def doTest():

    stake_addr_ext = callcli(3, 'getnewextaddress')

    logging.info('Enabling coldstaking, spending node 1, staking node 3')
    callcli(1, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_ext})))

    logging.info('sending 20000 PART to coldstaking script in 4 txns')
    internal_chain_1 = getInternalChain(1)['chain']
    logging.info('internal_chain_1 {}'.format(json.dumps(internal_chain_1, indent=4)))
    txids = []
    for i in range(4):
        # change will also go to coldstaking addresses
        callcli(1, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_ext})))
        outputs = [{'address': internal_chain_1, 'stakeaddress': stake_addr_ext, 'amount': 500.0, 'subfee': True}]
        txids.append(callcli(1, 'sendtypeto part part "{}"'.format(dumpje(outputs))))

    logging.info('Syncing mempool...')
    for txid in txids:
        waitForMempool(0, txid, delay_event)

    logging.info('Staking...')
    stakeBlocks(0, 1, delay_event)

    test_commands = ('getbalances', 'getwalletinfo', 'getstakinginfo', 'getcoldstakinginfo')
    results_before = {}
    for i in (1, 2, 3):
        rl = []
        for j in range(4):
            rl.append(callcli(i, test_commands[j]))
            #logging.info('node {}, {}: {}'.format(i, test_commands[j], json.dumps(rl[-1], indent=4)))
        results_before[i] = rl

    logging.info('Set same coldstaking change address on node 2 (mirror of node 1)')
    callcli(2, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_ext})))

    results_after = {}
    for i in (2,):
        rl = []
        for j in range(4):
            rl.append(callcli(i, test_commands[j]))
            #logging.info('node {}, {}: {}'.format(i, test_commands[j], json.dumps(rl[-1], indent=4)))
        results_after[i] = rl

    rl_b = results_before[1]
    rl_a = results_after[2]
    for i in range(4):
        if test_commands[i] == 'getwalletinfo':
            del rl_b[i]['keypoololdest']
            del rl_a[i]['keypoololdest']
        s_b = json.dumps(rl_b[i])
        s_a = json.dumps(rl_a[i])
        assert(s_a == s_b), 'wallet data mismatch {}: {} {}'.format(test_commands[i], s_b, s_a)

    r = callcli(1, 'extkey key {}'.format(stake_addr_ext))
    logging.info('extkey 1 {}'.format(json.dumps(r, indent=4)))

    r = callcli(2, 'extkey import {}'.format(stake_addr_ext))

    r = callcli(2, 'extkey options {} receive_on true'.format(stake_addr_ext))
    logging.info('extkey options {}'.format(json.dumps(r, indent=4)))

    r = callcli(2, 'extkey')
    logging.info('2 extkey {}'.format(json.dumps(r, indent=4)))

    logging.info('Restarting node 2')
    callcli(2, 'stop')
    delay_event.wait(10)
    if delay_event.is_set():
        raise ValueError('Exited')
    startDaemon(2, PARTICL_BINDIR)

    waitForDaemonRpc(2, delay_event)

    try:
        callcli(2, 'getwalletinfo')
    except Exception as e:
        logging.info('Loading wallet for node: {}'.format(2))
        callcli(2, 'loadwallet wallet')

    r = callcli(2, 'extkey')
    logging.info('2 extkey {}'.format(json.dumps(r, indent=4)))

    # Rescan from start of chain or earliest key
    r = callcli(2, 'rescanblockchain 0')

    r = callcli(2, 'extkey key {}'.format(stake_addr_ext))
    logging.info('extkey 2 {}'.format(json.dumps(r, indent=4)))


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
        waitForDaemonRpc(i, delay_event)

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
    callcli(2, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    callcli(3, 'extkeyimportmaster "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')

    try:
        doTest()
        logging.info('Test Passed!')
    except Exception:
        traceback.print_exc()
        logging.info('Test Failed.')

    logging.info('Stopping nodes.')
    delay_event.set()
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
