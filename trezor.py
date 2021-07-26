#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=/tmp/partbuild/src; python3 trezor.py

"""

import os
import json
import sys
import shutil
import signal
import logging
import threading
import traceback
import subprocess
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje

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
    callrpc(node_id, 'reservebalance true 0')
    waitForHeight(node_id, height)


def stakeBlocks(node_id, num_blocks):
    height = int(callrpc(node_id, 'getblockcount'))
    stakeToHeight(node_id, height + num_blocks)


def doTest():

    logging.info('Initialising account, see device:')
    callrpc(2, 'initaccountfromdevice')

    addr_2 = callrpc(2, 'getnewaddress normal_address')
    addr_2_b = callrpc(2, 'getnewaddress normal_address_to_receive_from_blind')
    addr_2_a = callrpc(2, 'getnewaddress normal_address_to_receive_from_anon')
    addr_1_cs = callrpc(1, 'getnewaddress normal_address_for_coldstaking')
    addr_1_cs = callrpc(1, 'validateaddress {} true'.format(addr_1_cs))['stakeonly_address']
    sx_addr_2 = callrpc(2, 'devicegetnewstealthaddress stealth_v2_address')
    big_addr_2 = callrpc(2, 'getnewaddress 256bit_address false false true')
    addr_1 = callrpc(1, 'getnewaddress ')
    sx_addr_0 = callrpc(0, 'getnewstealthaddress')
    sx_addr_1 = callrpc(1, 'getnewstealthaddress')

    callrpc(0, 'sendtoaddress {} {}'.format(addr_2, 10))

    outputs = [{'address': sx_addr_0, 'amount': 20}, {'address': sx_addr_1, 'amount': 2}]
    for i in range(4):
        callrpc(0, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))
    callrpc(0, 'sendtypeto part blind "{}"'.format(dumpje([{'address': sx_addr_0, 'amount': 20}])))

    logging.info('Staking...')
    stakeBlocks(0, 2)
    waitForHeight(2, 2)
    balances_0 = callrpc(0, 'getbalances')
    assert(balances_0['mine']['anon_trusted'] > 0)

    logging.info('Sending from normal to normal address:')
    txid = callrpc(2, 'sendtoaddress {} {}'.format(addr_2, 1.0))
    logging.info('txid: {}'.format(txid))
    logging.info('Waiting for txid {} to be in mempool'.format(txid))
    waitForMempool(0, txid)

    logging.info('Sending from normal to 256bit address:')
    txid_256bit = callrpc(2, 'sendtoaddress {} {}'.format(big_addr_2, 1.1))
    logging.info('txid_256bit: {}'.format(txid_256bit))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_256bit))
    waitForMempool(0, txid_256bit)

    unspent = callrpc(2, 'listunspent 0 9999999 \"[]\" true')

    use_inputs = []
    for utxo in unspent:
        if len(utxo['scriptPubKey']) < 70:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})

    assert(len(use_inputs) == 2)
    logging.info('Sending from normal to stealth address with two inputs:')
    opts = {'inputs': use_inputs}
    txid_to_stealth = callrpc(2, 'sendtypeto part part "{}" "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.2}]), dumpje(opts)))
    logging.info('txid_to_stealth: {}'.format(txid_to_stealth))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_to_stealth))
    waitForMempool(0, txid_to_stealth)

    tx_to_stealth = callrpc(2, 'gettransaction {}'.format(txid_to_stealth))
    tx_to_stealth = callrpc(2, 'decoderawtransaction {}'.format(tx_to_stealth['hex']))
    assert(len(tx_to_stealth['vin']) == 2)

    logging.info('Sending from normal change, 256bit and stealth to coldstake address, no change:')

    unspent = callrpc(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    total = 0
    for utxo in unspent:
        total += utxo['amount']
        use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 3)

    logging.info('total: {}'.format(total))
    opts = {'inputs': use_inputs}
    txid_to_cs = callrpc(2, 'sendtypeto part part "{}" "{}"'.format(dumpje([{'address': big_addr_2, 'stakeaddress': addr_1_cs, 'amount': total, 'subfee': True}]), dumpje(opts)))
    logging.info('txid_to_cs: {}'.format(txid_to_cs))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_to_cs))
    waitForMempool(0, txid_to_cs)

    tx_to_cs = callrpc(2, 'gettransaction {}'.format(txid_to_cs))
    tx_to_cs = callrpc(2, 'decoderawtransaction {}'.format(tx_to_cs['hex']))
    assert(len(tx_to_cs['vin']) == 3)
    assert(len(tx_to_cs['vout']) == 1)

    unspent = callrpc(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from cs to normal address:')
    txid_from_cs = callrpc(2, 'sendtoaddress {} {}'.format(addr_2, 1.4))
    logging.info('txid_from_cs: {}'.format(txid_from_cs))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_cs))
    waitForMempool(0, txid_from_cs)

    txid_a2p = callrpc(0, 'sendtypeto anon part "{}"'.format(dumpje([{'address': addr_2_b, 'amount': 2.11}])))
    txid_b2p = callrpc(0, 'sendtypeto blind part "{}"'.format(dumpje([{'address': addr_2_a, 'amount': 2.12}])))
    logging.info('Staking...')
    stakeBlocks(0, 1)
    waitForHeight(2, 3)

    unspent = callrpc(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        if utxo['txid'] == txid_a2p:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from coin received from anon:')
    opts = {'inputs': use_inputs}
    txid_from_anon = callrpc(2, 'sendtypeto part part "{}" "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.5}]), dumpje(opts)))
    logging.info('txid_from_anon: {}'.format(txid_from_anon))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_anon))
    waitForMempool(0, txid_from_anon)

    unspent = callrpc(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        if utxo['txid'] == txid_b2p:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from coin received from blind:')
    opts = {'inputs': use_inputs}
    txid_from_blind = callrpc(2, 'sendtypeto part part "{}" "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.6}]), dumpje(opts)))
    logging.info('txid_from_blind: {}'.format(txid_from_blind))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_blind))
    waitForMempool(0, txid_from_blind)

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
