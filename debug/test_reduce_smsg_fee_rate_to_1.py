#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=/tmp/partbuild/src; python3 test_reduce_smsg_fee_rate_to_1.py
cp /tmp/partbuild/src/particld /tmp/particld
cp /tmp/partbuild/src/particl-cli /tmp/particl-cli
export PARTICL_BINDIR=/tmp/; python3 test_reduce_smsg_fee_rate_to_1.py


Notes
    setting \\"smsgfeeratetarget\\":\\"0\\" is disabling it
    fee rate is set for consensus.smsg_fee_period (50 blocks in regtest)


Results:
getblockcount 1650
smsggetfeerate 1

getblockcount 2106
smsggetfeerate 235


"""

import os
import re
import sys
import json
import random
import shutil
import signal
import logging
import threading
import traceback
import subprocess
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje, format8, COIN
from distutils.util import strtobool
from util_tests import (
    DATADIRS, PARTICL_BINDIR, startDaemon, callcli,
    waitForDaemonRpc, stakeBlocks, getInternalChain, waitForMempool)


NUM_NODES = 4
BASE_PORT = 14792
BASE_RPC_PORT = 19792
DEBUG_MODE = True
RESET_DATA = True
PERSIST = strtobool(os.getenv('PERSIST', '0'))
EXTRA_CONFIG_JSON = json.loads(os.getenv('EXTRA_CONFIG_JSON', '{}'))
PATH_TO_SCRIPT = os.path.expanduser(os.getenv('PATH_TO_SCRIPT', '../'))

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

        if str(node_id) in EXTRA_CONFIG_JSON:
            for opt in EXTRA_CONFIG_JSON[str(node_id)]:
                fp.write(opt + '\n')

        for i in range(0, NUM_NODES):
            if node_id == i:
                continue
            fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))


def doTest():

    callcli(0, 'reservebalance false')

    num_1 = 0
    change_dir = False
    num_200 = 0
    print('walletsettings stakingoptions', json.dumps(callcli(0, 'walletsettings stakingoptions'), indent=4))

    while not delay_event.is_set():
        blocks = callcli(0, 'getblockcount')
        smsgfeerate = callcli(0, f'smsggetfeerate {blocks}')
        print('getblockcount', blocks)
        print('smsggetfeerate', json.dumps(smsgfeerate, indent=4))

        if smsgfeerate < 2:
            num_1 += 1
        else:
            num_1 = 0

        if num_1 > 10:
            staking_opts = callcli(0, 'walletsettings stakingoptions')['stakingoptions']
            staking_opts['smsgfeeratetarget'] = '0.0001'
            callcli(0, 'walletsettings stakingoptions "{}"'.format(dumpje(staking_opts)))
            print('walletsettings stakingoptions', json.dumps(callcli(0, 'walletsettings stakingoptions'), indent=4))
            num_1 = 0
            change_dir = True

        if change_dir is True:
            if smsgfeerate > 200:
                num_200 += 1
            else:
                num_200 = 0
        if change_dir and num_200 > 10:
            return True


        delay_event.wait(20)



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

        if i == 0:
            callcli(i, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"100\\",\\"stakesplitthreshold\\":200, \\"smsgfeeratetarget\\":\\"0.00000001\\"}"')
        else:
            callcli(i, 'walletsettings stakingoptions "{\\"enabled\\":false}"')
        callcli(i, 'reservebalance true 1000000')

    callcli(0, 'extkeygenesisimport "abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb"')
    callcli(1, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    callcli(2, 'extkeyimportmaster "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')
    callcli(3, 'extkeyimportmaster "graine article givre hublot encadrer admirer stipuler capsule acajou paisible soutirer organe"')

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
