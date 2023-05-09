#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2023 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""
export PARTICL_BINDIR=/tmp/partbuild/src; python3 test_qt.py

$PARTICL_BINDIR/qt/particl-qt --regtest --datadir=/tmp/parttest/3

Triggers missing blinding factor bug on versions <= 23.1.4

"""

import os
import sys
import json
import time
import shutil
import random
import signal
import logging
import threading
import traceback
import subprocess
import multiprocessing
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje, dumpj
from util_tests import (
    DATADIRS, PARTICL_BINDIR, startDaemon, callcli,
    stakeBlocks, waitForHeight)


NUM_NODES = 4
BASE_PORT = 14732
BASE_RPC_PORT = 19732
RESET_DATA = True

delay_event = threading.Event()


def signalHandler(sig, frame):
    print('Signal {} detected, ending.'.format(sig))
    delay_event.set()


def startQt(node_id, bindir):
    node_dir = os.path.join(DATADIRS, str(node_id))
    command_cli = os.path.join(bindir, 'particl-qt')

    args = [command_cli, '--version']
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()
    dversion = out[0].decode('utf-8').split('\n')[0]

    logging.info('Starting node ' + str(node_id) + '    ' + dversion + '\n'
                 + 'particl-qt' + ' ' + '-datadir=' + node_dir + '\n')
    args = [command_cli, '-datadir=' + node_dir, '-server']
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


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

        fp.write('debug=hdwallet\n')
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


def debug_task():
    while True:
        if delay_event.is_set():
            break

        try:
            dbg = callcli(1, 'debugwallet')
            if 'errors' in dbg and len(dbg['errors']) > 0:
                print(dbg)
        except Exception:
            pass

        time.sleep(1.0)


def doTest():

    callcli(0, 'reservebalance false')

    signal.signal(signal.SIGINT, signalHandler)

    sxaddr1 = callcli(1, 'getnewstealthaddress')

    txids = []
    for i in range(20):
        outputs = [{'address': sxaddr1, 'amount': 1.0}]
        callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))

    outputs = []
    sx_addrs = []
    for i in range(120):
        sx_addrs.append(callcli(1, 'getnewstealthaddress'))
        outputs.append({'address': sx_addrs[-1], 'amount': 10.0})

    password = 'testpass'
    rv = callcli(1, 'encryptwallet "{}"'.format(password))
    logging.info('encryptwallet {}, testpass: {}'.format(password, rv))

    callcli(1, f'walletpassphrase {password} 600')
    callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))
    callcli(1, 'walletlock')

    callcli(1, f'walletpassphrase {password} 600')
    callcli(1, 'sendtypeto part blind "{}"'.format(dumpje(outputs)))
    callcli(1, 'walletlock')

    for i in range(1000):
        delay_event.wait(5)

        callcli(1, f'walletpassphrase {password} 600')

        balances = callcli(1, 'getbalances')
        print(balances)

        if balances['mine']['blind_trusted'] > 200:
            to_type = random.choice(['blind', 'anon'])
            outputs = []
            for i in range(random.randint(0, 120)):
                outputs.append({'address': sx_addrs[0], 'amount': 1.0})
            try:
                callcli(1, 'sendtypeto blind {} "{}"'.format(to_type, dumpje(outputs)))
            except Exception as e:
                print(str(e))
                if 'too long of a mempool chain' in str(e):
                    pass
                else:
                    raise(e)

        if balances['mine']['anon_trusted'] > 200:
            to_type = random.choice(['blind', 'anon'])
            outputs = []
            for i in range(random.randint(0, 120)):
                outputs.append({'address': sx_addrs[0], 'amount': 1.0})
            try:
                callcli(1, 'sendtypeto anon {} "{}"'.format(to_type, dumpje(outputs)))
            except Exception as e:
                print(str(e))
                if 'too long of a mempool chain' in str(e):
                    pass
                else:
                    raise(e)

        callcli(1, 'walletlock')

    delayseconds = 90000
    print(f'Delaying for {delayseconds} seconds')
    print('Ctrl+c to quit')
    delay_event.wait(delayseconds)

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
        if i == 3 or i == 1:
            startQt(i, os.path.join(PARTICL_BINDIR, 'qt'))
        else:
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
            print(callcli(i, 'getwalletinfo'))
        except Exception as e:
            logging.info('Creating wallet for node: {}'.format(i))
            callcli(i, 'createwallet wallet')

        if i < 2:
            callcli(i, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"100\\",\\"stakesplitthreshold\\":200}"')
        callcli(i, 'reservebalance true 1000000')

    callcli(0, 'extkeygenesisimport "abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb"')
    callcli(1, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    callcli(2, 'extkeygenesisimport "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')
    m3 = callcli(3, 'mnemonic new')['mnemonic']
    logging.info(f'Importing mnemonic to node3: {m3}')
    callcli(3, 'extkeyimportmaster "{}"'.format(m3))

    process = multiprocessing.Process(target=debug_task)
    process.start()

    try:
        doTest()
    except Exception:
        traceback.print_exc()

    logging.info('Test Complete.')

    delay_event.set()

    print('Waiting for the process...')
    process.join()

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
