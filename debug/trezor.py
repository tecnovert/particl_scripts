#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

export PARTICL_BINDIR=~/tmp/particl-0.19.2.13/bin/; python3 trezor.py
export PARTICL_BINDIR=/tmp/partbuild/src; python3 trezor.py

"""

import os
import sys
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

    logging.info('Initialising account, see device:')
    callcli(2, 'initaccountfromdevice')

    addr_2 = callcli(2, 'getnewaddress normal_address')
    addr_2_b = callcli(2, 'getnewaddress normal_address_to_receive_from_blind')
    addr_2_a = callcli(2, 'getnewaddress normal_address_to_receive_from_anon')
    addr_1_cs = callcli(1, 'getnewaddress normal_address_for_coldstaking')
    addr_1_cs = callcli(1, 'validateaddress {} true'.format(addr_1_cs))['stakeonly_address']

    # getnewstealthaddress should fail
    try:
        sxaddr = callcli(2, 'getnewstealthaddress')
        assert False, 'getnewstealthaddress should fail'
    except Exception as e:
        assert('NewStealthKeyFromAccount failed' in str(e))

    sx_addr_2 = callcli(2, 'devicegetnewstealthaddress stealth_v2_address')
    big_addr_2 = callcli(2, 'getnewaddress 256bit_address false false true')
    addr_1 = callcli(1, 'getnewaddress ')
    sx_addr_0 = callcli(0, 'getnewstealthaddress')
    sx_addr_1 = callcli(1, 'getnewstealthaddress')

    callcli(0, 'sendtoaddress {} {}'.format(addr_2, 10))

    outputs = [{'address': sx_addr_0, 'amount': 20}, {'address': sx_addr_1, 'amount': 2}]
    for i in range(4):
        callcli(0, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))
    callcli(0, 'sendtypeto part blind "{}"'.format(dumpje([{'address': sx_addr_0, 'amount': 20}])))

    logging.info('Staking...')
    stakeBlocks(0, 2, delay_event)
    waitForHeight(2, 2, delay_event)
    balances_0 = callcli(0, 'getbalances')
    assert(balances_0['mine']['anon_trusted'] > 0)

    logging.info('Sending from normal to normal address:')
    txid = callcli(2, 'sendtoaddress {} {}'.format(addr_2, 1.0))
    logging.info('txid: {}'.format(txid))
    logging.info('Waiting for txid {} to be in mempool'.format(txid))
    waitForMempool(0, txid)

    logging.info('Sending from normal to 256bit address:')
    txid_256bit = callcli(2, 'sendtoaddress {} {}'.format(big_addr_2, 1.1))
    logging.info('txid_256bit: {}'.format(txid_256bit))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_256bit))
    waitForMempool(0, txid_256bit)

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')

    use_inputs = []
    for utxo in unspent:
        if len(utxo['scriptPubKey']) < 70:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})

    assert(len(use_inputs) == 2)
    logging.info('Sending from normal to stealth address with two inputs:')
    opts = {'inputs': use_inputs}
    txid_to_stealth = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.2}]), dumpje(opts)))
    logging.info('txid_to_stealth: {}'.format(txid_to_stealth))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_to_stealth))
    waitForMempool(0, txid_to_stealth)

    tx_to_stealth = callcli(2, 'gettransaction {}'.format(txid_to_stealth))
    tx_to_stealth = callcli(2, 'decoderawtransaction {}'.format(tx_to_stealth['hex']))
    assert(len(tx_to_stealth['vin']) == 2)

    logging.info('Sending from normal change, 256bit and stealth to coldstake address, no change:')

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    total = 0
    for utxo in unspent:
        total += utxo['amount']
        use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 3)

    logging.info('total: {}'.format(total))
    opts = {'inputs': use_inputs}
    txid_to_cs = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': big_addr_2, 'stakeaddress': addr_1_cs, 'amount': total, 'subfee': True}]), dumpje(opts)))
    logging.info('txid_to_cs: {}'.format(txid_to_cs))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_to_cs))
    waitForMempool(0, txid_to_cs)

    tx_to_cs = callcli(2, 'gettransaction {}'.format(txid_to_cs))
    tx_to_cs = callcli(2, 'decoderawtransaction {}'.format(tx_to_cs['hex']))
    assert(len(tx_to_cs['vin']) == 3)
    assert(len(tx_to_cs['vout']) == 1)

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from cs to normal address:')
    txid_from_cs = callcli(2, 'sendtoaddress {} {}'.format(addr_2, 1.4))
    logging.info('txid_from_cs: {}'.format(txid_from_cs))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_cs))
    waitForMempool(0, txid_from_cs)

    txid_a2p = callcli(0, 'sendtypeto anon part "{}"'.format(dumpje([{'address': addr_2_b, 'amount': 2.11}])))
    txid_b2p = callcli(0, 'sendtypeto blind part "{}"'.format(dumpje([{'address': addr_2_a, 'amount': 2.12}])))
    logging.info('Staking...')
    stakeBlocks(0, 1, delay_event)
    waitForHeight(2, 3, delay_event)

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        if utxo['txid'] == txid_a2p:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from coin received from anon:')
    opts = {'inputs': use_inputs}
    txid_from_anon = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.5}]), dumpje(opts)))
    logging.info('txid_from_anon: {}'.format(txid_from_anon))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_anon))
    waitForMempool(0, txid_from_anon)

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        if utxo['txid'] == txid_b2p:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)

    logging.info('Sending from coin received from blind:')
    opts = {'inputs': use_inputs}
    txid_from_blind = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': sx_addr_2, 'amount': 1.6}]), dumpje(opts)))
    logging.info('txid_from_blind: {}'.format(txid_from_blind))
    logging.info('Waiting for txid {} to be in mempool'.format(txid_from_blind))
    waitForMempool(0, txid_from_blind)

    logging.info('Testing receiving on stealth address from locked wallet')
    balances_before = callcli(2, 'getbalances')
    logging.info('Encrypting wallet')
    callcli(2, 'encryptwallet testpass')
    txid = callcli(1, 'sendtoaddress {} 10'.format(sx_addr_2))
    logging.info('txid: {}'.format(txid))
    tx = callcli(1, 'gettransaction {}'.format(txid))
    callcli(0, 'sendrawtransaction {}'.format(tx['hex']))
    waitForMempool(0, txid)
    logging.info('Staking')
    stakeBlocks(0, 1, delay_event)
    balances_after = callcli(2, 'getbalances')

    logging.info('Trusted before {}, after: {}'.format(balances_before['mine']['trusted'], balances_after['mine']['trusted']))
    assert(balances_after['mine']['trusted'] == balances_before['mine']['trusted'] + 10.0)

    unspent = callcli(2, 'listunspent 0 9999999 \"[]\" true')
    use_inputs = []
    for utxo in unspent:
        if utxo['txid'] == txid:
            use_inputs.append({'tx': utxo['txid'], 'n': utxo['vout']})
    assert(len(use_inputs) == 1)
    opts = {'inputs': use_inputs}

    logging.info('Testing sending from sx received while encrypted')
    try:
        txid_while_encrypted = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': sx_addr_0, 'amount': 1.7}]), dumpje(opts)))
        assert False, 'sendtypeto while locked should fail'
    except Exception as e:
        assert('Wallet locked' in str(e))
    callcli(2, 'walletpassphrase testpass 60')

    txid_while_encrypted = callcli(2, 'sendtypeto part part "{}" "" "" 5 1 false "{}"'.format(dumpje([{'address': sx_addr_0, 'amount': 1.7}]), dumpje(opts)))
    logging.info('txid_while_encrypted: {}'.format(txid_while_encrypted))
    waitForMempool(0, txid_while_encrypted)

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
