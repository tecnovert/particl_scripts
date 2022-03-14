#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

PARTICL_BINDIR=/tmp/partbuild/src python3 test_electrum.py

PERSIST=1 PARTICL_BINDIR=~/tmp/particl-0.21.2.7/bin/ python3 test_electrum.py

Notes:
    Node connected to electrumx must have txindex active
    reservebalance applies per wallet
    Blocks until spend and stake (nStakeMinConfirmations) maturity is reduced as chain starts.
"""

__VERSION__ = '0.1'

import os
import sys
import json
import shutil
import signal
import logging
import threading
import traceback
import subprocess
from contrib.rpcauth import generate_salt, password_to_hmac
from util import dumpje, strtobool
from util_tests import (
    DATADIRS, PARTICL_BINDIR, startDaemon, callcli,
    waitForDaemonRpc, stakeBlocks, waitForMempool)


NUM_NODES = 4
BASE_PORT = 14792
BASE_RPC_PORT = 19792
DEBUG_MODE = True
RESET_DATA = True
PERSIST = strtobool(os.getenv('PERSIST', '0'))
EXTRA_CONFIG_JSON = json.loads(os.getenv('EXTRA_CONFIG_JSON', '{}'))
GET_ADDR_INFO_FIXED = strtobool(os.getenv('GET_ADDR_INFO_FIXED', '0'))  # >= 0.19.2.20

ELECTRUMX_SRC_DIR = os.getenv('ELECTRUMX_SRC_DIR', os.path.expanduser('~/tmp/work/particl/electrum/electrumx'))
ELECTRUM_SRC_DIR = os.getenv('ELECTRUM_SRC_DIR', os.path.expanduser('~/tmp/work/particl/electrum/electrum/'))
ELECTRUM_VENV = os.getenv('ELECTRUM_VENV', os.path.expanduser('~/tmp/work/particl/electrum/venv_electrum'))

delay_event = threading.Event()


def startElectrumX(node_id):
    logging.info('\nStarting ElectrumX')

    rv = subprocess.run(f' git -C {ELECTRUMX_SRC_DIR} describe', capture_output=True, shell=True)
    logging.info('git describe: ' + rv.stdout.strip().decode('utf-8'))

    datadir = DATADIRS
    electrumx_dir = os.path.join(datadir, str(node_id), 'electrumx')

    if os.path.exists(electrumx_dir):
        shutil.rmtree(electrumx_dir)
    os.makedirs(electrumx_dir)

    sh_path = os.path.join(datadir, 'electrumx_{}.sh'.format(node_id))
    if os.path.exists(sh_path):
        os.remove(sh_path)

    with open(sh_path, 'w+') as fp:
        fp.write('#!/bin/bash\n')
        fp.write('source ' + ELECTRUM_VENV + '/bin/activate\n')
        fp.write('export SERVICES="ssl://:51002"\n')
        fp.write('export COIN=Particl\n')
        fp.write('export DAEMON_URL=http://test:test@127.0.0.1:19793\n')
        fp.write('export NET=regtest\n')
        fp.write('export CACHE_MB=400\n')
        fp.write('export DB_DIRECTORY={}/db\n'.format(electrumx_dir))
        fp.write('export SSL_CERTFILE={}/certfile.crt\n'.format(electrumx_dir))
        fp.write('export SSL_KEYFILE={}/keyfile.key\n'.format(electrumx_dir))
        fp.write('export BANNER_FILE={}/banner\n'.format(electrumx_dir))
        fp.write('mkdir -p $DB_DIRECTORY\n')

        fp.write('echo "TEST BANNER" > {}/banner\n'.format(electrumx_dir))
        fp.write('openssl req -nodes -new -x509 -keyout $SSL_KEYFILE -out $SSL_CERTFILE -subj /C=CA/ST=Quebec/L=Montreal/O="Poutine LLC"/OU=devops/CN=*.poutine.net\n')

        fp.write('cd {}\n'.format(ELECTRUMX_SRC_DIR))
        fp.write('./electrumx_server\n')

    fp_mp = open(os.path.join(electrumx_dir, 'stdout.txt'), 'w')
    args = 'bash {}'.format(sh_path)
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=fp_mp, stderr=fp_mp, shell=True, preexec_fn=os.setsid)

    return p, fp_mp


def startElectrum(node_id):
    logging.info('\nStarting Electrum')

    rv = subprocess.run(f' git -C {ELECTRUM_SRC_DIR} describe', capture_output=True, shell=True)
    logging.info('git describe: ' + rv.stdout.strip().decode('utf-8'))

    datadir = DATADIRS
    electrum_dir = os.path.join(datadir, str(node_id), 'electrum')

    if os.path.exists(electrum_dir):
        shutil.rmtree(electrum_dir)
    os.makedirs(electrum_dir)

    sh_path = os.path.join(datadir, 'electrum_{}.sh'.format(node_id))
    if os.path.exists(sh_path):
        os.remove(sh_path)

    with open(sh_path, 'w+') as fp:
        fp.write('#!/bin/bash\n')
        fp.write('cd {}\n'.format(ELECTRUM_SRC_DIR))
        fp.write('./electrum-env --regtest -vdebug -D {} daemon\n'.format(electrum_dir))

    fp_mp = open(os.path.join(electrum_dir, 'stdout.txt'), 'w')
    args = 'bash {}'.format(sh_path)
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=fp_mp, stderr=fp_mp, shell=True, preexec_fn=os.setsid)

    return p, fp_mp


def run_loop(addr256_node2, addr256_node2_2, extaddr_hotwallet):

    while not delay_event.is_set():
        print('run_loop')
        if True:
            outputs = [{'address': addr256_node2, 'amount': 1.0}]
            txid = callcli(1, 'sendtypeto {} {} "{}"'.format('part', 'part', dumpje(outputs)))
            logging.info('sendtypeto 256: {}'.format(txid))

        if True:
            outputs = [{'address': addr256_node2_2, 'amount': 1.1, 'stakeaddress': extaddr_hotwallet}]
            txid = callcli(1, 'sendtypeto {} {} "{}"'.format('part', 'part', dumpje(outputs)))
            logging.info('sendtypeto cs: {}'.format(txid))
        delay_event.wait(30.0)


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

        if node_id == 1:
            fp.write('txindex=1\n')

        if str(node_id) in EXTRA_CONFIG_JSON:
            for opt in EXTRA_CONFIG_JSON[str(node_id)]:
                fp.write(opt + '\n')

        for i in range(0, NUM_NODES):
            if node_id == i:
                continue
            fp.write('addnode=127.0.0.1:{}\n'.format(BASE_PORT + i))


def sync_and_stake(txids):
    logging.info('Syncing mempool...')
    for txid in txids:
        waitForMempool(0, txid, delay_event)
    print('Staking...')
    stakeBlocks(0, 1, delay_event)


def waitForElectrumDaemon():
    logging.info('\nWaiting for electrum daemon connection')
    electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
    electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)

    for i in range(30):
        print('Waiting for connection to electrum daemon')
        delay_event.wait(2)
        if delay_event.is_set():
            raise ValueError('Test stopped')
        try:
            rv = subprocess.run(electrum_bin + ' getinfo', capture_output=True, shell=True)
            data = json.loads(rv.stdout.decode('utf8'))
            if data['connected'] is True:
                return True
        except Exception as e:
            print('e', e)

    raise ValueError('waitForElectrumDaemon timed out')


def waitForElectrumBalance(min_balance):
    logging.info(f'\nWaiting for electrum balance: {min_balance}')
    electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
    electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)

    for i in range(100):
        delay_event.wait(5)
        if delay_event.is_set():
            raise ValueError('Test stopped')

        try:
            rv = subprocess.run(electrum_bin + ' getbalance', capture_output=True, shell=True)
            data = json.loads(rv.stdout.decode('utf8'))
            if float(data['confirmed']) >= min_balance:
                return True
        except Exception as e:
            print('e', e)

        print('Staking...')
        stakeBlocks(0, 1, delay_event)

    raise ValueError('waitForElectrumBalance timed out')


def waitForElectrumTXO(txid):
    logging.info(f'\nWaiting for electrum txo: {txid}')
    electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
    electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)

    for i in range(100):
        delay_event.wait(5)
        if delay_event.is_set():
            raise ValueError('Test stopped')

        try:
            rv = subprocess.run(electrum_bin + ' getinfo', capture_output=True, shell=True)
            data = json.loads(rv.stdout.strip().decode('utf-8'))
            print('e getinfo height', data['blockchain_height'])
            rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
            data = json.loads(rv.stdout.strip().decode('utf-8'))
            for utxo in data:
                if utxo['prevout_hash'] == txid:
                    return True
        except Exception as e:
            print('e', e)

        print('Staking...')
        stakeBlocks(0, 1, delay_event)

    raise ValueError('waitForElectrumTXO timed out')


def doTest():

    m1 = callcli(3, 'mnemonic new')['mnemonic']
    m2 = callcli(3, 'mnemonic new')['mnemonic']
    callcli(3, 'createwallet coldwallet')
    callcli(3, 'createwallet hotwallet')
    wallets3 = callcli(3, 'listwallets')
    assert(len(wallets3) == 3)
    assert('coldwallet' in wallets3)
    assert('hotwallet' in wallets3)

    callcli(3, '-rpcwallet={} extkeyimportmaster "{}"'.format('coldwallet', m1))
    callcli(3, '-rpcwallet={} extkeyimportmaster "{}"'.format('hotwallet', m2))

    logging.info('Creating anon outputs')
    txids = []
    sxaddr1 = callcli(1, 'getnewstealthaddress')
    for i in range(20):
        outputs = [{'address': sxaddr1, 'amount': 1.0}]
        txids.append(callcli(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs))))
    outputs = [{'address': sxaddr1, 'amount': 10.0}]
    txids.append(callcli(1, 'sendtypeto part blind "{}"'.format(dumpje(outputs))))
    logging.info('waiting for mempool')
    for txid in txids:
        waitForMempool(0, txid, delay_event)

    # Get address in stakeonly encoding
    addr_node3_cs = callcli(3, '-rpcwallet={} getnewaddress "{}"'.format('hotwallet', 'addr256_node2_cs'))
    validateaddress_addr_node3_cs = callcli(3, '-rpcwallet={} validateaddress "{}" true'.format('hotwallet', addr_node3_cs))
    addr_cs_stake = validateaddress_addr_node3_cs['stakeonly_address']
    logging.info('hotwallet staking address: ' + addr_cs_stake)

    electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
    electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)

    logging.info('Setting electrum coldstakingchangeaddress')
    subprocess.run(electrum_bin + f' cs_set_stakechangeaddress "{addr_cs_stake}"', capture_output=True, shell=True)
    rv = subprocess.run(electrum_bin + ' cs_view_stakechangeaddress', capture_output=True, shell=True)
    assert(rv.stdout.strip().decode('utf-8') == addr_cs_stake)

    addr256_node2 = callcli(2, 'getnewaddress "{}" {} {} {}'.format('256bit addr', 'false', 'false', 'true'))
    extaddr_hotwallet = callcli(3, '-rpcwallet={} getnewextaddress "{}"'.format('hotwallet', 'coldstaking addr'))
    addr256_node2_2 = callcli(2, 'getnewaddress "{}" {} {} {}'.format('256bit addr', 'false', 'false', 'true'))

    addr_info_addr256_node2_2 = callcli(2, f'getaddressinfo {addr256_node2_2}')
    key_index = addr_info_addr256_node2_2['path'].split('/')[-1]
    key_info = callcli(2, f'deriverangekeys {key_index}')
    addr_p2pkh = key_info[0]
    addr_info_addr_p2pkh = callcli(2, f'getaddressinfo {addr_p2pkh}')
    assert(addr_info_addr256_node2_2['pubkey'] == addr_info_addr_p2pkh['pubkey'])

    logging.info('Test electrum shows the correct 256bit address version')
    electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
    electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)

    rv = subprocess.run(electrum_bin + f' cs_show_256bit_address "{addr_p2pkh}"', capture_output=True, shell=True)
    electrum_addr0_256 = rv.stdout.strip().decode('utf-8')
    assert(electrum_addr0_256 == addr256_node2_2)
    logging.info(electrum_addr0_256)

    rv = subprocess.run(electrum_bin + ' getunusedaddress', capture_output=True, shell=True)
    electrum_addr0 = rv.stdout.strip().decode('utf-8')

    stakeBlocks(0, 1, delay_event)

    outputs = [{'address': electrum_addr0, 'amount': 100.0}]
    txid = callcli(1, 'sendtypeto {} {} "{}"'.format('part', 'part', dumpje(outputs)))
    logging.info('sent to electrum_addr0: {}'.format(txid))

    sync_and_stake((txid, ))

    waitForElectrumBalance(100.0)

    logging.info('electrum listunspent after receiving on standard address')
    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info(json.dumps(data, indent=4))
    assert(len(data) == 1)

    logging.info('Send a small amount so the change goes into coldstaking script')

    # Disable hotwallet staking
    rv = callcli(3, '-rpcwallet={} reservebalance true 100000'.format('hotwallet'))

    addr1 = callcli(1, 'getnewaddress')

    rv = subprocess.run(electrum_bin + f' payto {addr1} 0.1', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    txdecoded = callcli(2, f'decoderawtransaction {txhex}')
    assert(len(txdecoded['vout']) == 2)
    cs_utxo = None
    for utxo in txdecoded['vout']:
        if 'stakeaddresses' in utxo['scriptPubKey']:
            cs_utxo = utxo
            break

    logging.info('Decoded utxo {}'.format(json.dumps(cs_utxo, indent=4)))

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')

    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))

    assert(data[0]['spend_address'] == cs_utxo['scriptPubKey']['addresses'][0])
    assert(data[0]['stake_address'] == addr_cs_stake)

    logging.info('Confirm coldstaking outputs can be spent')
    old_cs_utxo = cs_utxo
    rv = subprocess.run(electrum_bin + f' payto {addr1} 0.1', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    txdecoded = callcli(2, f'decoderawtransaction {txhex}')
    assert(len(txdecoded['vout']) == 2)
    cs_utxo = None
    for utxo in txdecoded['vout']:
        if 'stakeaddresses' in utxo['scriptPubKey']:
            cs_utxo = utxo
            break

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')

    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))

    assert(data[0]['spend_address'] != old_cs_utxo['scriptPubKey']['addresses'][0])  # Change should go to a new address
    assert(data[0]['spend_address'] == cs_utxo['scriptPubKey']['addresses'][0])
    assert(data[0]['stake_address'] == addr_cs_stake)

    logging.info('Waiting for coldstaking output to stake')
    print('Staking 40 blocks...')
    for i in range(4):
        stakeBlocks(0, 10, delay_event)
        delay_event.wait(1)

    # Enable hotwallet staking
    rv = callcli(3, '-rpcwallet={} reservebalance false'.format('hotwallet'))

    old_txid = txid
    has_staked = False
    for i in range(1000):
        delay_event.wait(5)
        if delay_event.is_set():
            raise ValueError('Test stopped')

        try:
            rv = subprocess.run(electrum_bin + ' getinfo', capture_output=True, shell=True)
            data = json.loads(rv.stdout.strip().decode('utf-8'))
            print('e getinfo height', data['blockchain_height'])
            rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
            data = json.loads(rv.stdout.strip().decode('utf-8'))
            if len(data) < 1 or data[0]['prevout_hash'] != old_txid:
                has_staked = True
                break
        except Exception as e:
            print('e', e)

        print('Staking...')
        stakeBlocks(0, 1, delay_event)

    assert(has_staked)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    assert(len(data) == 1)

    logging.info('Balance should be maturing')
    rv = subprocess.run(electrum_bin + ' getbalance', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info(json.dumps(data, indent=4))
    assert(float(data['confirmed']) == 0.0)
    assert(float(data['unmatured']) > 99.0)

    logging.info('Test insufficient balance while maturing')
    rv = subprocess.run(electrum_bin + f' payto {addr1} 10', capture_output=True, shell=True)
    assert('Insufficient funds' in rv.stderr.strip().decode('utf-8'))

    logging.info('Test outputs can be spent once matured')

    logging.info('Set static spend changeaddress')
    old_cs_utxo = cs_utxo
    addr256 = old_cs_utxo['scriptPubKey']['addresses'][0]

    logging.info('cs_list_spendchangeaddresses after adding address')
    subprocess.run(electrum_bin + f' cs_add_spendchangeaddress "{addr256}"', capture_output=True, shell=True)
    rv = subprocess.run(electrum_bin + ' cs_list_spendchangeaddresses', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info(json.dumps(data, indent=4))
    assert(len(data) == 1)
    assert(data[0] == addr256)

    logging.info('cs_list_spendchangeaddresses after removing address')
    rv = subprocess.run(electrum_bin + f' cs_remove_spendchangeaddress "{addr256}"', capture_output=True, shell=True)
    rv = subprocess.run(electrum_bin + ' cs_list_spendchangeaddresses', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info(json.dumps(data, indent=4))
    assert(len(data) == 0)

    logging.info('cs_list_spendchangeaddresses after adding address back')
    subprocess.run(electrum_bin + f' cs_add_spendchangeaddress "{addr256}"', capture_output=True, shell=True)
    rv = subprocess.run(electrum_bin + f' cs_add_spendchangeaddress "{addr256}"', capture_output=True, shell=True)
    assert('Address exists' in rv.stderr.strip().decode('utf-8'))
    rv = subprocess.run(electrum_bin + ' cs_list_spendchangeaddresses', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info(json.dumps(data, indent=4))
    assert(len(data) == 1)
    assert(data[0] == addr256)

    # Disable hotwallet staking
    rv = callcli(3, '-rpcwallet={} reservebalance true 100000'.format('hotwallet'))

    print('Staking 120 blocks...')
    for i in range(12):
        stakeBlocks(0, 10, delay_event)
        delay_event.wait(1)

    waitForElectrumBalance(99)

    logging.info('payto should succeed once outputs have matured')
    rv = subprocess.run(electrum_bin + f' payto {addr1} 10', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')

    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))

    assert(data[0]['prevout_hash'] == txid)
    assert(data[0]['spend_address'] == old_cs_utxo['scriptPubKey']['addresses'][0])
    assert(data[0]['stake_address'] == addr_cs_stake)

    logging.info('Confirm removing the coldstakingchangeaddress disables coldstaking')
    subprocess.run(electrum_bin + ' cs_set_stakechangeaddress ""', capture_output=True, shell=True)
    rv = subprocess.run(electrum_bin + ' cs_view_stakechangeaddress', capture_output=True, shell=True)
    assert(rv.stdout.strip().decode('utf-8') == '')

    rv = subprocess.run(electrum_bin + f' payto {addr1} 0.1', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    txdecoded = callcli(2, f'decoderawtransaction {txhex}')
    assert(len(txdecoded['vout']) == 2)
    change_utxo = None
    for utxo in txdecoded['vout']:
        if utxo['value'] > 0.1:
            change_utxo = utxo
            break
    assert(change_utxo is not None)
    logging.info(json.dumps(txdecoded['vout'], indent=4))

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')
    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    logging.info('electrum listunspent ' + json.dumps(data, indent=4))
    assert(len(data) == 1)
    assert('spend_address' not in data[0])
    assert('stake_address' not in data[0])

    logging.info('Test spending A->P outputs')
    outputs = [{'address': electrum_addr0, 'amount': 5.0}]
    txid = callcli(1, 'sendtypeto {} {} "{}" "" "" 5 1'.format('anon', 'part', dumpje(outputs)))
    logging.info('sent to electrum_addr0: {}'.format(txid))

    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    assert(len(data) == 2)

    rv = subprocess.run(electrum_bin + ' getunusedaddress', capture_output=True, shell=True)
    electrum_addr1 = rv.stdout.strip().decode('utf-8')
    rv = subprocess.run(electrum_bin + f' payto {electrum_addr1} !', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    txdecoded = callcli(2, f'decoderawtransaction {txhex}')
    assert(len(txdecoded['vin']) == 2)

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')
    waitForElectrumTXO(txid)

    logging.info('Test spending B->P outputs')
    outputs = [{'address': electrum_addr0, 'amount': 5.0}]
    txid = callcli(1, 'sendtypeto {} {} "{}" "" "" 5 1'.format('blind', 'part', dumpje(outputs)))
    logging.info('sent to electrum_addr0: {}'.format(txid))

    waitForElectrumTXO(txid)

    rv = subprocess.run(electrum_bin + ' listunspent', capture_output=True, shell=True)
    data = json.loads(rv.stdout.strip().decode('utf-8'))
    assert(len(data) == 2)

    rv = subprocess.run(electrum_bin + f' payto {electrum_addr1} !', capture_output=True, shell=True)
    txhex = rv.stdout.strip().decode('utf-8')

    txdecoded = callcli(2, f'decoderawtransaction {txhex}')
    assert(len(txdecoded['vin']) == 2)

    rv = subprocess.run(electrum_bin + f' broadcast {txhex}', capture_output=True, shell=True)
    txid = rv.stdout.strip().decode('utf-8')
    waitForElectrumTXO(txid)


    if PERSIST:
        callcli(0, 'reservebalance false')
        callcli(0, 'walletsettings stakelimit "%s"' % (dumpje({'height': 0})))

        update_thread = threading.Thread(target=run_loop, args=(addr256_node2, addr256_node2_2, extaddr_hotwallet))
        update_thread.start()

        while not delay_event.is_set():
            logging.info('Persist mode active, height {}, ctrl+c to quit'.format(callcli(0, 'getblockcount')))

            delay_event.wait(20)

        update_thread.join()

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
    callcli(2, 'extkeyimportmaster "squeeze number usual island type hamster skin attend cute mango stone sauce"')
    callcli(3, 'extkeyimportmaster "graine article givre hublot encadrer admirer stipuler capsule acajou paisible soutirer organe"')

    electrumx, electrumx_fp = startElectrumX(1)
    electrum, electrum_fp = startElectrum(1)

    try:
        waitForElectrumDaemon()

        logging.info('Creating electrum wallet from mnemonic')
        electrum_dir = os.path.join(DATADIRS, str(1), 'electrum')
        mnemonic = 'squeeze number usual island type hamster skin attend cute mango stone sauce'
        electrum_bin = ELECTRUM_SRC_DIR + 'electrum-env --regtest -vdebug -D {}'.format(electrum_dir)
        subprocess.run(electrum_bin + f' restore "{mnemonic}"', capture_output=True, shell=True)
        subprocess.run(electrum_bin + ' load_wallet', capture_output=True, shell=True)

        rv = subprocess.run(electrum_bin + ' getunusedaddress', capture_output=True, shell=True)
        electrum_addr0 = rv.stdout.strip().decode('utf-8')

        node2_addr0 = callcli(2, 'deriverangekeys 0')[0]
        assert(node2_addr0 == electrum_addr0)

        doTest()
    except Exception:
        traceback.print_exc()

    logging.info('Stopping electrumx.')
    os.killpg(os.getpgid(electrumx.pid), signal.SIGTERM)
    electrumx_fp.close()

    logging.info('Stopping electrum.')
    os.killpg(os.getpgid(electrum.pid), signal.SIGTERM)
    electrum_fp.close()

    delay_event.set()
    logging.info('Stopping nodes.')
    for i in range(0, NUM_NODES):
        callcli(i, 'stop')

    logging.info('Test Complete.')


def main():
    if not os.path.exists(DATADIRS):
        os.makedirs(DATADIRS)

    with open(os.path.join(DATADIRS, 'test.log'), 'w') as fp:
        logger = logging.getLogger()
        logger.level = logging.DEBUG
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.addHandler(logging.StreamHandler(fp))

        logging.info(os.path.basename(sys.argv[0]) + f' v{__VERSION__}\n\n')
        runTest(RESET_DATA)

    print('Done.')


if __name__ == '__main__':
    main()
