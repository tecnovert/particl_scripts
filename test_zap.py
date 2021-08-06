#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=~/tmp/particl-0.19.2.12/bin/; python3 test_zap.py

export PARTICL_BINDIR=/tmp/partbuild/src; python3 test_zap.py

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

PARTICL_BINDIR = os.path.expanduser(os.getenv('PARTICL_BINDIR', '.'))
PARTICLD = 'particld'
PARTICL_CLI = 'particl-cli'
PARTICL_TX = 'particl-tx'

DATADIRS = '/tmp/parttest'

NUM_NODES = 3
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


def startDaemon(node_id, bindir):
    node_dir = os.path.join(DATADIRS, str(node_id))
    command_cli = os.path.join(bindir, PARTICLD)

    args = [command_cli, '--version']
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()
    dversion = out[0].decode('utf-8').split('\n')[0]

    args = [command_cli, '-datadir=' + node_dir]

    logging.info('Starting node ' + str(node_id) + '    ' + dversion + '\n'
                 + PARTICLD + ' ' + '-datadir=' + node_dir + '\n')
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()

    if len(out[1]) > 0:
        print('error ', out[1])
    return [out[0], out[1]]


def callrpc(node_id, cmd):
    node_dir = os.path.join(DATADIRS, str(node_id))
    command_cli = os.path.join(PARTICL_BINDIR, PARTICL_CLI)
    args = command_cli + ' -datadir=' + node_dir + ' -rpcuser=test -rpcpassword=test ' + cmd
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out = p.communicate()
    r = out[0]
    re = out[1]
    if re and len(re) > 0:
        raise ValueError('RPC error ' + str(re))
    try:
        ro = json.loads(r)
        return ro
    except Exception:
        r = r.decode('utf-8').strip()
    return r


def waitForMempool(node, txid, nTries=10):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForMempool stopped.')
        try:
            ro = callrpc(node, 'getmempoolentry {}'.format(txid))
        except Exception:
            continue
        return True
    raise ValueError('waitForMempool timed out.')


def waitForHeight(node, nHeight, nTries=500):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForHeight stopped.')
        ro = callrpc(node, 'getblockchaininfo')
        if ro['blocks'] >= nHeight:
            return True
    raise ValueError('waitForHeight timed out.')


def stakeToHeight(node_id, height):
    callrpc(node_id, 'walletsettings stakelimit "%s"' % (dumpje({'height': height})))
    callrpc(node_id, 'reservebalance false')
    waitForHeight(node_id, height)


def stakeBlocks(node_id, num_blocks):
    height = int(callrpc(node_id, 'getblockcount'))
    stakeToHeight(node_id, height + num_blocks)


def getInternalChain(node_id):
    account = callrpc(node_id, 'extkey account')
    for c in account['chains']:
        if 'function' in c and c['function'] == 'active_internal':
            return c
    raise ValueError('Internal chain not found.')


def doTest():

    stake_addr = callrpc(1, 'getnewaddress')
    stake_addr_2 = callrpc(1, 'getnewaddress')
    stake_addr_ext = callrpc(1, 'getnewextaddress')

    addr2 = []
    for i in range(20):
        addr2.append(callrpc(2, 'getnewaddress'))
    addr2_sx0 = callrpc(2, 'getnewstealthaddress')

    txids = []
    for i in range(20):
        txids.append(callrpc(1, 'sendtoaddress {} {}'.format(addr2[i], format8(random.randint(0.001 * COIN, 10 * COIN)))))

    txids.append(callrpc(1, 'sendtoaddress {} {}'.format(addr2_sx0, 1.111)))

    logging.info('Syncing mempool...')
    for txid in txids:
        waitForMempool(0, txid)

    logging.info('Staking...')
    stakeBlocks(0, 1)

    datadir_2 = os.path.join(DATADIRS, '2')

    logging.info('testing zap maxinputs=1...')
    ic_before = getInternalChain(2)
    args = ['./zap.py', '--loop=false', '--maxinputs=1', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)
    ic_after = getInternalChain(2)
    assert(int(ic_after['num_derives']) == int(ic_before['num_derives']) + 1)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)

    txid = sent_txids[0]
    tx = callrpc(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr)

    logging.info('testing zap nomix=true...')
    args = ['./zap.py', '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callrpc(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr)

    logging.info('testing zap infer stakeaddress...')
    r = callrpc(2, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_2})))
    args = ['./zap.py', '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callrpc(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == stake_addr_2)

    logging.info('testing zap infer stakeaddress extaddress...')
    expect_addr = callrpc(2, 'deriverangekeys 0 0 {}'.format(stake_addr_ext))[0]
    r = callrpc(2, 'walletsettings changeaddress "{}"'.format(dumpje({'coldstakingaddress': stake_addr_ext})))
    args = ['./zap.py', '--loop=false', '--nomix=true', '--network=regtest', '--datadir', datadir_2]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) == 1)
    txid = sent_txids[0]
    tx = callrpc(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 1)
    assert(tx['decoded']['vout'][0]['scriptPubKey']['stakeaddresses'][0] == expect_addr)
    r = callrpc(2, 'extkey key {}'.format(stake_addr_ext))
    assert(int(r['num_derives']) == 1)

    logging.info('testing zap testonly...')
    unspents_before = callrpc(2, 'listunspent')
    assert(len(unspents_before) > 3)
    args = ['./zap.py', '--testonly=1', '--minwait=1', '--maxwait=1', '--maxinputs=3', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)
    unspents_after = callrpc(2, 'listunspent')
    assert(len(unspents_before) == len(unspents_after))
    created_txids = re.findall('Test tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(created_txids) > 3)

    logging.info('testing zap maxinputs=3...')
    args = ['./zap.py', '--minwait=1', '--maxwait=1', '--maxinputs=3', '--network=regtest', '--datadir', datadir_2, stake_addr]
    result = subprocess.run(args, capture_output=True)

    sent_txids = re.findall('Sent tx: (.*?),', result.stdout.decode(), re.DOTALL)
    assert(len(sent_txids) > 3)
    txid = sent_txids[0]
    tx = callrpc(2, 'gettransaction {} true true'.format(txid))
    assert(len(tx['decoded']['vin']) == 3)

    logging.info('Test Passed!')


def runTest(resetData):
    logging.info('Installing signal handler')
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
                callrpc(i, 'getnetworkinfo')
            except Exception as e:
                delay_event.wait(1)
                continue
            break
        if k >= num_tries - 1:
            raise ValueError('Can\'t contact node ' + str(i))

        try:
            callrpc(i, 'getwalletinfo')
        except Exception as e:
            logging.info('Creating wallet for node: {}'.format(i))
            callrpc(i, 'createwallet wallet')

        if i < 2:
            callrpc(i, 'walletsettings stakingoptions "{\\"stakecombinethreshold\\":\\"100\\",\\"stakesplitthreshold\\":200}"')
        callrpc(i, 'reservebalance true 1000000')

    callrpc(0, 'extkeygenesisimport "abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb"')
    callrpc(1, 'extkeyimportmaster "pact mammal barrel matrix local final lecture chunk wasp survey bid various book strong spread fall ozone daring like topple door fatigue limb olympic" "" false "Master Key" "Default Account" 0 "{\\"createextkeys\\": 1}"')
    callrpc(2, 'extkeygenesisimport "sección grito médula hecho pauta posada nueve ebrio bruto buceo baúl mitad"')

    try:
        doTest()
    except Exception:
        traceback.print_exc()

    logging.info('Test Complete.')

    delay_event.set()

    logging.info('Stopping nodes.')
    for i in range(0, NUM_NODES):
        callrpc(i, 'stop')


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
