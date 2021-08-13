#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=~/tmp/particl-0.19.2.13/bin/; python3 test_zap.py
export PARTICL_BINDIR=/tmp/partbuild/src; python3 test_zap.py

export PERSIST=1
export EXTRA_CONFIG_JSON="{\"1\":[\"zmqpubhashblock=tcp://127.0.0.1:36750\",\"zmqpubsmsg=tcp://127.0.0.1:36750\",\"zmqpubhashtx=tcp://127.0.0.1:36750\"]}"
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

    stake_addr = callcli(1, 'getnewaddress')
    stake_addr_2 = callcli(1, 'getnewaddress')
    stake_addr_ext = callcli(1, 'getnewextaddress')

    addr2 = []
    for i in range(20):
        addr2.append(callcli(2, 'getnewaddress'))
    addr2_sx0 = callcli(2, 'getnewstealthaddress')

    txids = []
    for i in range(20):
        txids.append(callcli(1, 'sendtoaddress {} {}'.format(addr2[i], format8(random.randint(0.001 * COIN, 10 * COIN)))))

    txids.append(callcli(1, 'sendtoaddress {} {}'.format(addr2_sx0, 1.111)))

    logging.info('Syncing mempool...')
    for txid in txids:
        waitForMempool(0, txid, delay_event)

    logging.info('Staking...')
    stakeBlocks(0, 1, delay_event)

    datadir_2 = os.path.join(DATADIRS, '2')
    datadir_3 = os.path.join(DATADIRS, '3')

    zap_path = os.path.join(PATH_TO_SCRIPT, 'zap.py')

    logging.info('Testing zap maxinputs=1...')
    ic_before = getInternalChain(2)
    args = [zap_path, '--loop=false', '--maxinputs=1', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)
    ic_after = getInternalChain(2)
    assert(int(ic_after['num_derives']) == int(ic_before['num_derives']) + 1)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)

    txid = sent_txids[0]
    tx = callcli(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr)

    logging.info('Testing zap nomix=true...')
    args = [zap_path, '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callcli(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr)

    logging.info('Testing zap infer stakeaddress...')
    r = callcli(2, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_2})))
    args = [zap_path, '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callcli(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr_2)

    logging.info('Testing zap infer stakeaddress extaddress...')
    expect_addr = callcli(2, 'deriverangekeys 0 0 {}'.format(stake_addr_ext))[0]
    callcli(2, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_ext})))
    args = [zap_path, '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callcli(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == expect_addr)
    r = callcli(2, 'extkey key {}'.format(stake_addr_ext))
    assert(int(r['num_derives']) == 1)

    logging.info('Testing zap testonly...')
    unspents_before = callcli(2, 'listunspent')
    assert(len(unspents_before) > 3)
    args = [zap_path, '--testonly=1', '--minwait=1', '--maxwait=1', '--maxinputs=3', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)
    unspents_after = callcli(2, 'listunspent')
    assert(len(unspents_before) == len(unspents_after))
    created_txids = re.findall('Test tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(created_txids) > 3)

    logging.info('Testing zap maxinputs=3...')
    args = [zap_path, '--minwait=1', '--maxwait=1', '--maxinputs=3', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) > 3)
    txid = sent_txids[0]
    tx = callcli(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 3)

    logging.info('Testing addressgroupings')
    addr3 = []
    for i in range(3):
        addr3.append(callcli(3, 'getnewaddress'))

    opts = {'show_hex': True, 'test_mempool_accept': True}
    txres1 = callcli(0, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': addr3[0], 'amount': 0.1}]), dumpje(opts)))
    txres2 = callcli(0, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': addr3[2], 'amount': 10.1}]), dumpje(opts)))
    # Speed up mempool syncing
    callcli(3, 'sendrawtransaction ' + txres1['hex'])
    callcli(3, 'sendrawtransaction ' + txres2['hex'])

    logging.info('Syncing mempool...')
    txids = (txres1['txid'], txres2['txid'])
    for txid in txids:
        waitForMempool(3, txid, delay_event)

    logging.info('Staking...')
    stakeBlocks(0, 1, delay_event)

    addr2 = callcli(2, 'getnewaddress')
    txres1 = callcli(3, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': addr2, 'amount': 4}]), dumpje(opts)))
    # Speed up mempool syncing
    callcli(0, 'sendrawtransaction ' + txres1['hex'])
    logging.info('Staking...')
    stakeBlocks(0, 1, delay_event)

    addressgroupings = callcli(3, 'listaddressgroupings')
    assert(len(addressgroupings) == 2)
    assert(len(addressgroupings[0]) == 2 or len(addressgroupings[1]) == 2)

    args = [zap_path, '--minwait=1', '--maxwait=1', '--addressgroupings=true', '--network=regtest', '--datadir', datadir_3, stake_addr]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 2)
    txid = sent_txids[0]
    tx = callcli(3, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)

    txid = sent_txids[1]
    tx = callcli(3, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)

    logging.info('Test Passed!')

    if PERSIST:
        callcli(0, 'reservebalance false')
        callcli(0, 'walletsettings stakelimit "%s"' % (dumpje({'height': 0})))
        extkey2 = callcli(2, 'getnewextaddress staketest')
        logging.info('setting node 1 coldstaking change-address to: {}'.format(extkey2))
        callcli(1, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': extkey2})))
        while not delay_event.is_set():
            logging.info('Persist mode active, height {}, ctrl+c to quit'.format(callcli(0, 'getblockcount')))
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
            callcli(i, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"100\\",\\"stakesplitthreshold\\":200}"')
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
