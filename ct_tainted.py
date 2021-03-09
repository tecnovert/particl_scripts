#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-0.19.2.5/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile

rm -r /tmp/ct_tainted || true
mkdir -p /tmp/ct_tainted
python ct_tainted.py -outputdir=/tmp/ct_tainted -fromheight=0 -forktime=1614268800 > /tmp/ct_tainted.txt

2021-03-09
    num_ct 8693
    num_ct_spent 6572
    num_ct_outputs 8693
    num_unspent 2121
    num_tainted 1701
    num_unspent_txids 327
    num_unspent_txids_tainted 1350

    gettxoutsetinfo
        txouts_blinded 2121

"""

__version__ = '0.3'

import os
import sys
import json
import time
import signal
import logging
import traceback

from util import (
    open_rpc)


chain_stats = None
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')


class CTOutput():
    __slots__ = ('spent', 'tainted')

    def __init__(self, spent, tainted):
        self.spent = spent
        self.tainted = tainted


class Prevout():
    __slots__ = ('txid', 'n')

    def __init__(self, txid, n):
        self.txid = txid
        self.n = int(n)

    def __hash__(self):
        return hash((self.txid, self.n))

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return NotImplemented
        return self.txid == other.txid and self.n == other.n


class ChainTracker():
    def callrpc(self, method, params=[]):
        # TODO: Reusing the connection seems slower in linux
        for i in range(3):
            try:
                if self.rpc_conn is None:
                    self.rpc_conn = open_rpc(self.rpc_port, self.rpc_auth)
                try:
                    v = self.rpc_conn.json_request(method, params)
                    r = json.loads(v.decode('utf-8'))
                except Exception as e:
                    traceback.print_exc()
                    self.rpc_conn.close()
                    self.rpc_conn = None
                    raise ValueError('RPC Server Error')
                if 'error' in r and r['error'] is not None:
                    raise ValueError('RPC error ' + str(r['error']))
                return r['result']
            except Exception as e:
                logging.error('RPC Server Error, try {}: {}'.format(i, str(e)))
        raise ValueError('RPC retries failed.')

    def __init__(self, settings):
        self.is_running = True
        self.rpc_conn = None

        self.settings = settings

        self.particl_data_dir = os.path.expanduser(settings['data_dir'])
        self.chain = settings.get('chain', '')

        self.processed_height = settings.get('fromheight', 0)
        self.totime = settings.get('totime', 0)
        self.forktime = settings.get('forktime', 0)

        self.ct_outputs = {}
        self.num_ct_spent = 0

        # Wait for daemon to start
        authcookiepath = os.path.join(self.particl_data_dir, '' if self.chain == 'mainnet' else self.chain, '.cookie')
        for i in range(10):
            if not os.path.exists(authcookiepath):
                time.sleep(0.5)
        with open(authcookiepath) as fp:
            self.rpc_auth = fp.read()

        # Read rpc port from .conf file
        if 'rpcport' not in settings:
            configpath = os.path.join(self.particl_data_dir, '' if self.chain == 'mainnet' else self.chain, 'particl.conf')
            if os.path.exists(configpath):
                with open(configpath) as fp:
                    for line in fp:
                        if line.startswith('#'):
                            continue
                        pair = line.strip().split('=')
                        if len(pair) == 2:
                            if pair[0] == 'rpcport':
                                settings['rpcport'] = int(pair[1])
                                logging.info('Set rpcport from config file: {}.'.format(settings['rpcport']))

        self.rpc_port = settings.get('rpcport', 51735 if self.chain == 'mainnet' else 51935)

    def start(self):
        logging.info('Starting Chain stats script at height %d\n' % (self.processed_height))

        self.waitForDaemonRPC()

        r = self.callrpc('getnetworkinfo')
        logging.info('Particl Core version %s\n' % (r['version']))

    def stopRunning(self):
        self.is_running = False

    def waitForDaemonRPC(self):
        for i in range(21):
            if not self.is_running:
                return
            if i == 20:
                logging.error('Can\'t connect to daemon RPC, exiting.')
                self.stopRunning(1)
                return
            try:
                self.callrpc('getblockchaininfo')
                break
            except Exception as ex:
                traceback.print_exc()
                logging.warning('Can\'t connect to daemon RPC, trying again in %d second/s.' % (1 + i))
                time.sleep(1 + i)

    def processBlock(self, height):
        if height % 10000 == 0:
            logging.info('processBlock height %d' % (height))
            logging.info('num_ct %d' % (len(self.ct_outputs)))
            logging.info('num_ct_spent %d' % (self.num_ct_spent))

        blockhash = self.callrpc('getblockhash', [height, ])
        block = self.callrpc('getblock', [blockhash, 3])

        if self.totime > 0 and self.totime < block['time']:
            logging.info('Stopping before block {}, time {} > {}'.format(height, block['time'], self.totime))
            return False

        for tx in block['tx']:
            spends_tainted = False
            num_anon_in = 0

            for txi_n, tx_input in enumerate(tx['vin']):
                if 'coinbase' in tx_input:
                    continue
                if 'txid' in tx_input and tx_input['txid'] == '0000000000000000000000000000000000000000000000000000000000000000':
                    continue  # Coinbase

                if 'type' in tx_input and tx_input['type'] == 'anon':
                    num_anon_in += 1
                    continue

                try:
                    prevout = self.ct_outputs[Prevout(tx_input['txid'], tx_input['vout'])]
                except Exception:
                    # plain prevout
                    continue
                assert(prevout.spent is False)
                prevout.spent = True
                self.num_ct_spent += 1

                if prevout.tainted:
                    spends_tainted = True

            for tx_out in tx['vout']:
                if tx_out['type'] == 'blind' and block['time'] < self.forktime:
                    is_tainted = False
                    if num_anon_in > 0 or spends_tainted:
                        is_tainted = True
                    self.ct_outputs[Prevout(tx['txid'], tx_out['n'])] = CTOutput(False, is_tainted)

        self.processed_height = height
        return True


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    if chain_stats is not None:
        chain_stats.stopRunning()


def printHelp():
    print('ct_tainted.py --outputdir=path --datadir=path  --fromheight=x --totime=x --forktime=x')


def main():
    global chain_stats
    settings = {
        'chain': 'mainnet'
    }

    for v in sys.argv[1:]:
        if len(v) < 2 or v[0] != '-':
            logging.warning('Unknown argument', v)
            continue

        s = v.split('=')
        name = s[0].strip()

        for i in range(2):
            if name[0] == '-':
                name = name[1:]
        if name == 'h' or name == 'help':
            printHelp()
            return 0
        if name == 'testnet':
            settings['chain'] = 'testnet'
            continue
        if name == 'regtest':
            settings['chain'] = 'regtest'
            continue

        if len(s) == 2:
            if name == 'datadir':
                settings['data_dir'] = os.path.expanduser(s[1])
                continue
            if name == 'outputdir':
                settings['output_dir'] = os.path.expanduser(s[1])
                continue
            if name == 'fromheight':
                settings['fromheight'] = int(s[1])
                continue
            if name == 'totime':
                settings['totime'] = int(s[1])
                continue
            if name == 'forktime':
                settings['forktime'] = int(s[1])
                continue
        logging.warning('Unknown argument', v)

    if 'data_dir' not in settings:
        if os.name == 'nt':
            settings['data_dir'] = os.path.join(os.getenv('APPDATA'), 'Particl', '' if settings['chain'] == 'mainnet' else settings['chain'])
        else:
            settings['data_dir'] = os.path.join(os.path.expanduser('~/.particl'), '' if settings['chain'] == 'mainnet' else settings['chain'])

    logging.info('chain, data_dir: {}, {}'.format(settings['chain'], settings['data_dir']))

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logging.info('Ctrl + c to exit.')

    logging.info(os.path.basename(sys.argv[0]) + ', version: ' + __version__ + '\n\n')

    chain_stats = ChainTracker(settings)
    chain_stats.start()

    try:
        r = chain_stats.callrpc('getblockchaininfo')
        while r['blocks'] > chain_stats.processed_height and chain_stats.is_running:
            if not chain_stats.processBlock(chain_stats.processed_height + 1):
                break
    except Exception as ex:
        traceback.print_exc()

    chain_stats.output_dir = settings.get('output_dir', '.')
    if not os.path.exists(chain_stats.output_dir):
        os.makedirs(chain_stats.output_dir)

    unspent_txids = set()
    unspent_txids_tainted = set()
    num_unspent = 0
    num_tainted = 0
    for outpoint, cto in chain_stats.ct_outputs.items():
        if cto.spent is True:
            continue
        num_unspent += 1

        if cto.tainted is True:
            unspent_txids_tainted.add(outpoint.txid)
            num_tainted += 1
        else:
            unspent_txids.add(outpoint.txid)

    print('num_ct_outputs', len(chain_stats.ct_outputs))
    print('num_unspent', num_unspent)
    print('num_tainted', num_tainted)

    print('num_unspent_txids', len(unspent_txids))
    print('num_unspent_txids_tainted', len(unspent_txids_tainted))

    with open(os.path.join(chain_stats.output_dir, 'ct_unspent_txids.txt'), 'w') as fp:
        for txid in unspent_txids:
            fp.write('{},{}\n'.format(txid, 0))
        for txid in unspent_txids_tainted:
            fp.write('{},{}\n'.format(txid, 1))

    print('Done.')


if __name__ == '__main__':
    main()
