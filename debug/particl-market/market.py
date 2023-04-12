#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021-2023 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.


"""

git clone --branch regtest https://github.com/tecnovert/particl-market.git

export PARTICL_BINDIR=~/tmp/particl-23.0.3.0/bin/; python3 market.py

"""

import os
import json
import sys
import time
import select
import shutil
import signal
import decimal
import logging
import termios
import threading
import traceback
import subprocess

import hmac
from binascii import hexlify
from os import urandom
#from rpcauth import generate_salt, password_to_hmac


def generate_salt(size):
    """Create size byte hex salt"""
    return hexlify(urandom(size)).decode()


def password_to_hmac(salt, password):
    m = hmac.new(bytearray(salt, 'utf-8'), bytearray(password, 'utf-8'), 'SHA256')
    return m.hexdigest()


def toBool(s):
    return s.lower() in ['1', 'true']


COIN = 100000000


PARTICL_BINDIR = os.path.expanduser(os.getenv('PARTICL_BINDIR', '.'))
PARTICLD = os.getenv('PARTICLD', 'particld')
PARTICL_CLI = os.getenv('PARTICL_CLI', 'particl-cli')
PARTICL_TX = os.getenv('PARTICL_TX', 'particl-tx')
RESET_DATA = toBool(os.getenv('RESET_DATA', 'True'))
DEBUG_MODE = toBool(os.getenv('DEBUG_MODE', 'True'))

DATADIRS = '/tmp/parttest'
MP_SRC_DIR = os.getenv('MP_SRC_DIR', os.path.expanduser('~/particl-market'))
MP_TARGET_DIR = os.getenv('MP_TARGET_DIR', os.path.join(DATADIRS, 'mp'))

NUM_NODES = 5
BASE_PORT = 14792
BASE_RPC_PORT = 19792

APP_PORT = 3000
ZMQ_PORT = 54235

delay_event = threading.Event()


def dquantize(n):
    return n.quantize(decimal.Decimal(10) ** -8)


def jsonDecimal(obj):
    if isinstance(obj, decimal.Decimal):
        return str(obj)
    raise TypeError


def dumpj(jin):
    return json.dumps(jin, indent=4, default=jsonDecimal)


def signalHandler(sig, frame):
    logging.info('Signal {} detected, ending.'.format(sig))
    delay_event.set()


def writeConfig(datadir, nodeId, rpcPort, port):
    filePath = os.path.join(datadir, str(nodeId) + '/particl.conf')

    if os.path.exists(filePath):
        return

    with open(filePath, 'w+') as fp:
        fp.write('regtest=1\n')
        fp.write('[regtest]\n')

        fp.write('port=' + str(port) + '\n')
        fp.write('rpcport=' + str(rpcPort) + '\n')
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
        fp.write('displaylocaltime=1\n')
        fp.write('acceptnonstdtxn=0\n')
        fp.write('minstakeinterval=10\n')

        if nodeId >= 2 and nodeId <= 3:
            fp.write('txindex=1\n')
            fp.write('zmqpubsmsg=tcp://127.0.0.1:{}\n'.format(ZMQ_PORT + nodeId))


        for i in range(0, NUM_NODES):
            if nodeId == i:
                continue
            fp.write('addnode=127.0.0.1:%d\n' % (BASE_PORT + i))


def prepareDir(datadir, nodeId):
    nodeDir = os.path.join(datadir, str(nodeId))

    if not os.path.exists(nodeDir):
        os.makedirs(nodeDir)

    writeConfig(datadir, nodeId, BASE_RPC_PORT + nodeId, BASE_PORT + nodeId)


def dumpje(jin, replace_with='\\"'):
    return json.dumps(jin, default=jsonDecimal).replace('"', replace_with)


def callrpc3(nodeId, bindir, cmd):
    nodeDir = os.path.join(DATADIRS, str(nodeId))
    command_cli = os.path.join(bindir, PARTICL_CLI)
    args = command_cli + ' -datadir=' + nodeDir + ' ' + cmd
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out = p.communicate()

    if len(out[1]) > 0:
        print('error ', out[1])
    return [out[0], out[1]]


def callrpc2(nodeId, bindir, cmd):
    srv = ''
    r, re = callrpc3(nodeId, bindir, cmd)
    if re and len(re) > 0:
        raise ValueError('RPC error ' + str(re))
    elif r is None:
        srv = 'None'
    else:
        try:
            ro = json.loads(r)
            srv = dumpj(ro)
        except Exception:
            r = r.decode('utf-8').strip()
            srv = r
    return r


def callrpc(nodeId, cmd):
    return callrpc2(nodeId, PARTICL_BINDIR, cmd)


def callrpcj(nodeId, cmd):
    return json.loads(callrpc2(nodeId, PARTICL_BINDIR, cmd))


def startDaemon(nodeId, bindir, zmqServerSK=None):
    nodeDir = os.path.join(DATADIRS, str(nodeId))
    command_cli = os.path.join(bindir, PARTICLD)

    args = [command_cli, '--version']
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()
    dversion = out[0].decode('utf-8').split('\n')[0]

    args = [command_cli, '-datadir=' + nodeDir]
    if zmqServerSK is not None:
        args.append('-serverkeyzmq=%s' % (zmqServerSK))

    logging.info('Starting node ' + str(nodeId) + '    ' + dversion + '\n'
                 + PARTICLD + ' ' + '-datadir=' + nodeDir + '\n')
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()

    if len(out[1]) > 0:
        print('error ', out[1])
    return [out[0], out[1]]


def startMarket(nodeId):
    logging.info('startMarket ' + str(nodeId) + '\n')
    datadir = DATADIRS
    mp_dir = os.path.join(datadir, str(nodeId), 'mkt')

    if os.path.exists(mp_dir):
        shutil.rmtree(mp_dir)
    os.makedirs(mp_dir)

    env_path = os.path.join(datadir, 'mp_{}.env'.format(nodeId))
    if os.path.exists(env_path):
        os.remove(env_path)

    with open(env_path, 'w+') as fp:
        fp.write('NODE_ENV=test\n')
        #fp.write('NODE_ENV=development\n')
        fp.write('REGTEST=true\n')
        fp.write('REGTEST_PORT={}\n'.format(BASE_RPC_PORT + nodeId))
        fp.write('RPCUSER=test\n')
        fp.write('RPCPASSWORD=test\n')

        fp.write('APP_NAME=particl-market\n')
        fp.write('APP_HOST=http://localhost\n')
        fp.write('APP_URL_PREFIX=/api\n')
        fp.write('APP_PORT={}\n'.format(APP_PORT + nodeId))
        fp.write('RPCHOSTNAME=localhost\n')
        fp.write('JASMINE_TIMEOUT=100000\n')
        fp.write('TEST_BOOTSTRAP_WAITFOR=10\n')

        fp.write('STANDALONE=true\n')
        fp.write('DEFAULT_MARKETPLACE_NAME=DEFAULT\n')
        fp.write('DEFAULT_MARKETPLACE_PRIVATE_KEY=2Zc2pc9jSx2qF5tpu25DCZEr1Dwj8JBoVL5WP4H1drJsX9sP4ek\n')
        fp.write('DEFAULT_MARKETPLACE_ADDRESS=pmktyVZshdMAQ6DPbbRXEFNGuzMbTMkqAA\n')

        fp.write('APP_DEFAULT_PROFILE_ID=1\n')
        fp.write('APP_DEFAULT_MARKETPLACE_NAME=test_mp\n')
        fp.write('APP_DEFAULT_MARKETPLACE_PRIVATE_KEY=2Zc2pc9jSx2qF5tpu25DCZEr1Dwj8JBoVL5WP4H1drJsX9sP4ek\n')
        fp.write('PROFILE_DEFAULT_MARKETPLACE_ID=1\n')

        fp.write('PAID_MESSAGE_RETENTION_DAYS=7\n')
        fp.write('FREE_MESSAGE_RETENTION_DAYS=7\n')

        fp.write('MARKET_RPC_USER=test\n')
        fp.write('MARKET_RPC_PASSWORD=test\n')

        fp.write('LOG_LEVEL=debug\n')
        fp.write('LOG_ADAPTER=winston\n')

        fp.write('API_INFO_ENABLED=true\n')
        fp.write('API_INFO_ROUTE=/info\n')

        fp.write('CLI_ENABLED=true\n')
        fp.write('CLI_ROUTE=/cli\n')

        fp.write('MONITOR_ENABLED=true\n')
        fp.write('MONITOR_ROUTE=/status\n')

        fp.write('DATA_CHECK_DELAY=60\n')

        fp.write('CHASING_COINS_API=https://chasing-coins.com/api/v1/convert\n')
        fp.write('CHASING_COINS_API_DELAY=60\n')

        fp.write('LISTING_ITEMS_EXPIRED_INTERVAL=10\n')
        fp.write('PROPOSAL_RESULT_RECALCULATION_INTERVAL=30\n')

        fp.write('LISTING_ITEM_REMOVE_PERCENTAGE=0.1\n')
        fp.write('ZMQ_PORT={}\n'.format(ZMQ_PORT + nodeId))

    sh_path = os.path.join(datadir, 'mp_{}.sh'.format(nodeId))
    if os.path.exists(sh_path):
        os.remove(sh_path)

    with open(sh_path, 'w+') as fp:
        fp.write('#!/bin/bash\n')
        fp.write('export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"\n')
        fp.write('nvm use v16\n')
        fp.write('cd {}\n'.format(MP_TARGET_DIR))
        fp.write('START_FOR_TESTS=1 NODE_ENV=development MP_DATA_FOLDER={} MP_DOTENV_FILE={} yarn start\n'.format(mp_dir, env_path))

    fp_mp = open(os.path.join(mp_dir, 'stdout.txt'), 'w')
    args = 'bash {}'.format(sh_path)
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=fp_mp, stderr=fp_mp, shell=True, preexec_fn=os.setsid)
    #p.communicate(input=b'START\n')

    return p, fp_mp


def wait_for_height(node, nHeight, nTries=500):
    for i in range(nTries):
        time.sleep(1)
        ro = callrpcj(node, 'getblockchaininfo')
        if ro['blocks'] >= nHeight:
            return True
    return False


def waitForHeight(node, nHeight, nTries=500):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForHeight stopped.')
        ro = callrpcj(node, 'getblockchaininfo')
        if ro['blocks'] >= nHeight:
            return True
    raise ValueError('waitForHeight timed out.')


def stakeToHeight(nodeId, height):
    callrpc(nodeId, 'walletsettings stakelimit "%s"' % (dumpje({'height': height})))
    callrpc(nodeId, 'reservebalance true 0')
    try:
        waitForHeight(nodeId, height)
    except Exception as e:
        if 'stopped' not in str(e):
            raise(e)


def stakeBlocks(node_id, num_blocks):
    height = int(callrpc(node_id, 'getblockcount'))
    stakeToHeight(node_id, height + num_blocks)


def threadStake():
    while not delay_event.is_set():
        delay_event.wait(5)
        stakeBlocks(0, 1)


def marketRPC(port, method, params=[]):
    cmd_url = 'http://localhost:{}/api/rpc'.format(port)
    cmd_data = '{{\"method\":\"{}\",\"params\":{},\"id\":1,\"jsonrpc\":\"2.0\"}}'.format(method, dumpje(params, replace_with='\"'))
    args = ['curl', '-s',
            '--user', 'test:test',
            '-H', 'Accept: application/json',
            '-H', 'Content-Type:application/json',
            '-X', 'POST',
            '--data', cmd_data,
            cmd_url
            ]
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if result.returncode != 0 or len(result.stdout) == 0:
        raise ValueError('marketRPC failed {}'.format(result.stderr))

    json_rv = json.loads(result.stdout.decode())
    if 'error' in json_rv:
        raise ValueError('marketRPC failed {}'.format(json_rv['error']))

    return json_rv['result']


def waitForWallet(node_id, num_tries=20):
    for i in range(num_tries):
        rv = callrpcj(node_id, 'listwallets')
        if 'profiles/DEFAULT/particl-market' in rv:
            return True

        if i >= num_tries - 1 or delay_event.is_set():
            raise ValueError('Timed out waiting for node {} market wallet to exist.'.format(node_id))
        sleep_for = 1 + i // 2
        logging.info('Waiting for node {} market wallet to exist {}.'.format(node_id, sleep_for))
        delay_event.wait(sleep_for)


def waitForListing(port, market_string, listing_id, num_tries=60):
    for i in range(num_tries):
        rv = marketRPC(port, 'item', ['search', 0, 100, 'ASC', 'created_at', market_string])
        for listing in rv:
            if listing['id'] == listing_id:
                return True

        if i >= num_tries - 1 or delay_event.is_set():
            raise ValueError('Timed out waiting for listing.')
        sleep_for = 1 + i // 2
        logging.info('Waiting for listing {}, {}.'.format(listing_id, sleep_for))
        delay_event.wait(sleep_for)


def waitForBid(port, market_string, listing_id, num_tries=60):
    for i in range(num_tries):
        rv = marketRPC(port, 'item', ['search', 0, 100, 'ASC', 'created_at', market_string])
        for listing in rv:
            if listing['id'] == listing_id:
                if len(listing['Bids']) > 0:
                    return True

        if i >= num_tries - 1 or delay_event.is_set():
            raise ValueError('Timed out waiting for bid.')
        sleep_for = 1 + i // 5
        logging.info('Waiting for bid on listing {}, {}.'.format(listing_id, sleep_for))
        delay_event.wait(sleep_for)


def waitForOrderStatus(port, listing_id, order_id, status, num_tries=60):
    for i in range(num_tries):
        rv = marketRPC(port, 'order', ['search', 0, 10, 'ASC', 'created_at', listing_id])

        for order in rv:
            if order['id'] == order_id and len(order['OrderItems']) > 0:
                if order['OrderItems'][0]['status'] == status:
                    return True
        if i >= num_tries - 1 or delay_event.is_set():
            raise ValueError('Timed out waiting for bid.')
        sleep_for = 1 + i // 5
        logging.info('Waiting for order {} status {}, {}.'.format(order_id, status, sleep_for))
        delay_event.wait(sleep_for)


def doTest():
    num_tries = 40
    for i in range(40):
        try:
            marketRPC(3002, 'help')
            break
        except Exception as e:
            pass

        if i >= num_tries - 1 or delay_event.is_set():
            raise ValueError('Timed out waiting for market to start')

        sleep_for = 1 + i // 2
        logging.info('Waiting for market to respond {}.'.format(sleep_for))
        delay_event.wait(sleep_for)

    waitForWallet(2)
    waitForWallet(3)
    market_wallet_name = 'profiles/DEFAULT/particl-market'

    wallets2 = callrpcj(2, 'listwallets')
    print('2 listwallets', dumpj(wallets2))
    for wallet in wallets2:
        callrpc(2, '-rpcwallet={} reservebalance true 1000000'.format(wallet))

    wallets3 = callrpcj(3, 'listwallets')
    print('3 listwallets', dumpj(wallets3))
    for wallet in wallets3:
        callrpc(3, '-rpcwallet={} reservebalance true 1000000'.format(wallet))


    sxaddr2 = callrpc(2, '-rpcwallet={} getnewstealthaddress market_address'.format(market_wallet_name))
    sxaddr3 = callrpc(3, '-rpcwallet={} getnewstealthaddress market_address'.format(market_wallet_name))

    height = int(callrpc(1, 'getblockcount'))
    outputs = [{'address': sxaddr2, 'amount': 100}, {'address': sxaddr3, 'amount': 100}]
    for i in range(8):
        callrpc(1, 'sendtypeto part part "{}"'.format(dumpje(outputs)))
    for i in range(10):
        callrpc(1, 'sendtypeto part anon "{}"'.format(dumpje(outputs)))

    logging.info('Waiting for height: {}'.format(height + 1))
    wait_for_height(2, height + 1)
    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    #rv = marketRPC(3002, 'help', [])
    #print('help', rv)

    identity_id = 2
    MARKETPLACE_KEY = '2Zc2pc9jSx2qF5tpu25DCZEr1Dwj8JBoVL5WP4H1drJsX9sP4ek'
    rv = marketRPC(3002, 'market', ['add', 1, 'mymarket', 'MARKETPLACE', MARKETPLACE_KEY, MARKETPLACE_KEY, identity_id])
    print('market add 3002', dumpj(rv))

    rv = marketRPC(3002, 'profile', ['list', ])
    print('profile list 3002', dumpj(rv))

    rv = marketRPC(3002, 'market', ['list', 1])
    print('market list 3002', dumpj(rv))

    rv = marketRPC(3003, 'market', ['add', 1, 'mymarket', 'MARKETPLACE', MARKETPLACE_KEY, MARKETPLACE_KEY, identity_id])
    print('market add 3003', dumpj(rv))

    rv = marketRPC(3003, 'profile', ['list', ])
    print('profile list 3003', dumpj(rv))

    rv = marketRPC(3003, 'market', ['list', 1])
    print('market list 3003', dumpj(rv))

    category_id = 11
    rv = marketRPC(3002, 'template', ['add', 1, 'test template', 'for testing', 'for testing', category_id, 'SALE', 'PART', 10 * COIN, 1 * COIN, 1 * COIN])
    print('template add', dumpj(rv))
    template1_id = rv['id']
    market_id = 1

    rv = marketRPC(3002, 'location', ['update', template1_id, 'GB', '41 some road someplace'])
    print('location update', rv)

    rv = marketRPC(3002, 'template', ['clone', template1_id, market_id])
    print('template clone', rv)
    template_in_market_id = rv['id']

    rv = callrpcj(2, 'listwallets')
    print('2 listwallets', dumpj(rv))

    rv = marketRPC(3002, 'template', ['get', template_in_market_id])
    print('template get', dumpj(rv))

    assert(rv['ItemInformation']['ItemCategory']['id'] == category_id)
    rv = callrpcj(2, 'listwallets')
    print('2 listwallets', dumpj(rv))

    profile_id = 1
    rv = marketRPC(3002, 'identity', ['list', profile_id])
    print('identity list', dumpj(rv))

    rv = callrpcj(2, 'listwallets')
    print('2 listwallets', dumpj(rv))

    #rv = marketRPC(3002, 'identity', ['fund', identity_id, market_wallet_name, 100])
    #print('identity fund', dumpj(rv))

    rv = callrpcj(2, 'listwallets')
    print('2 listwallets', dumpj(rv))

    rv = callrpcj(2, '-rpcwallet={} listunspent'.format(market_wallet_name))
    print('2 listunspent', dumpj(rv))

    days_valid = 4
    rv = marketRPC(3002, 'template', ['post', template_in_market_id, days_valid])
    print('template post', dumpj(rv))

    rv = marketRPC(3002, 'market', ['list', 1])
    print('market list', dumpj(rv))
    market_string = rv[0]['receiveAddress']
    print('market list', dumpj(rv))
    logging.info('market_string: {}'.format(market_string))

    profile_id = 1
    rv = marketRPC(3003, 'address', ['list', profile_id])
    print('3 address list', dumpj(rv))

    rv = marketRPC(3003, 'address', ['add', profile_id, 'nowhere', 'Outis', 'Nemo', 't', 'o', 'k', 'y', 'ZW', '1'])
    print('3 address add', dumpj(rv))
    address_id = rv['id']

    listing_id = 1
    waitForListing(3003, market_string, listing_id)

    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    #rv = marketRPC(3003, 'identity', ['fund', identity_id, market_wallet_name, 100])
    #print('identity fund', dumpj(rv))
    #logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    rv = marketRPC(3003, 'bid', ['send', listing_id, identity_id, address_id])
    print('3 bid send', dumpj(rv))

    waitForBid(3002, market_string, listing_id)

    rv = marketRPC(3003, 'order', ['search', 0, 10, 'ASC', 'created_at', listing_id])
    print('before 3 order search', dumpj(rv))

    bid_id = 1
    for i in range(5):
        try:
            rv = marketRPC(3002, 'bid', ['accept', bid_id, identity_id])
            print('3 bid accept', dumpj(rv))

        except Exception as e:
            delay_for = 5
            logging.warning('bid accept failed, retrying in {} seconds'.format(delay_for))
            delay_event.wait(delay_for)
            continue
        break
    assert(rv['result'] is not None)

    rv = marketRPC(3003, 'order', ['search', 0, 10, 'ASC', 'created_at', listing_id])
    print('after 3 order search', dumpj(rv))

    logging.info('Wait for awaiting escrow.')
    order_id = 1
    waitForOrderStatus(3003, listing_id, order_id, 'AWAITING_ESCROW')

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    order_item_id = 1
    #rv = marketRPC(3002, 'escrow', ['lock', order_item_id])
    #print('2 escrow lock', dumpj(rv))

    rv = marketRPC(3003, 'escrow', ['lock', order_item_id])
    print('3 escrow lock', dumpj(rv))

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    logging.info('Wait for escrow locked')

    waitForOrderStatus(3002, listing_id, order_id, 'ESCROW_LOCKED')

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    rv = marketRPC(3002, 'escrow', ['complete', order_item_id])
    print('3 escrow complete', dumpj(rv))

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    logging.info('Wait for escrow completed')

    waitForOrderStatus(3003, listing_id, order_id, 'ESCROW_COMPLETED')

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    rv = marketRPC(3003, 'escrow', ['release', order_item_id])
    print('3 escrow release', dumpj(rv))

    waitForOrderStatus(3003, listing_id, order_id, 'COMPLETE')

    logging.info('2 getbalances {}'.format(dumpj(callrpcj(2, '-rpcwallet={} getbalances'.format(market_wallet_name)))))
    logging.info('3 getbalances {}'.format(dumpj(callrpcj(3, '-rpcwallet={} getbalances'.format(market_wallet_name)))))

    #rv = marketRPC(3003, 'escrow', ['release', order_item_id])
    #print('3 escrow release', dumpj(rv))

    rv = marketRPC(3003, 'item', ['search', 0, 10, 'ASC', 'created_at', market_string])
    print('3 item search', dumpj(rv))

    logging.info('Test passed!')


def runTest(resetData):
    if resetData:
        for i in range(NUM_NODES):
            dirname = os.path.join(DATADIRS, str(i))
            if os.path.isdir(dirname):
                logging.info('Removing' + dirname)
                shutil.rmtree(dirname)

    logging.info('\nPrepare the network')

    zmqServerPks = []

    for i in range(0, NUM_NODES):
        command_cli = os.path.join(PARTICL_BINDIR, PARTICLD)
        prepareDir(DATADIRS, i)
        startDaemon(i, PARTICL_BINDIR)

    for i in range(0, NUM_NODES):
        # Wait until all nodes are responding
        k = 0
        for k in range(10):
            try:
                r = callrpc3(i, PARTICL_BINDIR, 'getnetworkinfo')
                if len(r[1]) > 0:
                    raise ValueError('rpc error.')
            except Exception:
                time.sleep(1)
                continue
            break
        if k >= 10:
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

    callrpc(2, 'extkeyimportmaster "てつづき　いくぶん　ちょさくけん　たんご　でんち　おじぎ　てくび　やっぱり　たんさん　むろん　いちりゅう　たりょう"')
    callrpc(3, 'extkeyimportmaster "matar misa bambú vinagre abierto faja válido lista saber jugo dulce perico"')

    callrpc(4, 'extkeyimportmaster "cappero malafede sierra slitta vantaggio stima anacardo variante stampato ritegno istituto gonfio"')

    logging.info('Starting stake thread.')

    signal.signal(signal.SIGINT, signalHandler)
    stake_thread = threading.Thread(target=threadStake)
    stake_thread.start()

    if not os.path.isdir(MP_TARGET_DIR):
        logging.info('Preparing market code.')
        shutil.copytree(MP_SRC_DIR, MP_TARGET_DIR)

        sh_path = os.path.join(DATADIRS, 'mp.sh')
        if os.path.exists(sh_path):
            os.remove(sh_path)
        module_path = os.path.join(MP_TARGET_DIR, 'node_modules')
        if os.path.exists(module_path):
            shutil.rmtree(module_path)
        with open(sh_path, 'w+') as fp_mp:
            fp_mp.write('#!/bin/bash\n')
            fp_mp.write('export NVM_DIR="$HOME/.nvm"; [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"\n')
            fp_mp.write('nvm use v16\n')

            fp_mp.write('npm install -g wait-port\n')
            fp_mp.write('npm install -g -s --no-progress yarn\n')
            fp_mp.write('npm install -g ts-node\n')
            fp_mp.write('npm install -g tslint\n')
            fp_mp.write('npm install -g typescript\n')

            fp_mp.write('cd {}\n'.format(MP_TARGET_DIR))
            fp_mp.write('yarn install\n')

        with open(os.path.join(DATADIRS, 'mp_install.log'), 'w') as fp_mp:
            args = 'bash {}'.format(sh_path)
            p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=fp_mp, stderr=fp_mp, shell=True, preexec_fn=os.setsid)
            p.wait()

        appjs_path = os.path.join(MP_TARGET_DIR, 'dist', 'app.js')
        cmd = f"sed -i 's/exports.app = newApp;/start();\\nexports.app = newApp;/g' {appjs_path}"
        print('sed', cmd)
        subprocess.run(cmd, shell=True)


    mp2, mp2_fp = startMarket(2)
    mp3, mp3_fp = startMarket(3)

    try:
        doTest()
    except Exception:
        traceback.print_exc()

    logging.info('Test Complete.')

    logging.info('Stopping market clients.')
    os.killpg(os.getpgid(mp2.pid), signal.SIGTERM)
    os.killpg(os.getpgid(mp3.pid), signal.SIGTERM)
    mp2_fp.close()
    mp3_fp.close()

    delay_event.set()
    stake_thread.join()

    logging.info('Stopping nodes.')
    for i in range(0, NUM_NODES):
        callrpc(i, 'stop')


def main():
    if not os.path.exists(DATADIRS):
        os.makedirs(DATADIRS)

    # Save the terminal settings
    stdfd = sys.stdin.fileno()
    new_term = termios.tcgetattr(stdfd)
    old_term = termios.tcgetattr(stdfd)

    # New terminal settings unbuffered
    new_term[3] = (new_term[3] & ~termios.ICANON)
    termios.tcsetattr(stdfd, termios.TCSAFLUSH, new_term)

    with open(os.path.join(DATADIRS, 'test.log'), 'w') as fp:
        logger = logging.getLogger()
        logger.level = logging.DEBUG
        logger.addHandler(logging.StreamHandler(sys.stdout))
        logger.addHandler(logging.StreamHandler(fp))

        logging.info(os.path.basename(sys.argv[0]) + '\n\n')
        runTest(RESET_DATA)

    # Restore original terminal settings
    termios.tcsetattr(stdfd, termios.TCSAFLUSH, old_term)

    print('Done.')


if __name__ == '__main__':
    main()
