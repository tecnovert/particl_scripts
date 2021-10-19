#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

Extract the values of unfrozen pre-fork anon outputs.

~/tmp/particl-0.19.2.16/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile

rm -r /tmp/anon_post_fork || true
mkdir -p /tmp/anon_post_fork

python extract_anon_post_fork.py -outputdir=/tmp/extract_anon_post_fork > /tmp/extract_anon_post_fork.txt

"""

__version__ = '0.4'

import os
import sys
import json
import time
import signal
import decimal
import logging
import traceback

from util import (
    COIN,
    open_rpc)


MAX_MONEY = 21000000 * COIN
chain_app = None
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
WITH_PLAIN_OUTPUTS = False


class AnonOutValue:
    __slots__ = ('amount', 'known')

    def __init__(self, amount, known):
        self.amount = amount
        self.known = known


class CTOutput():
    __slots__ = ('value', 'known')

    def __init__(self, value, known):
        self.value = value
        self.known = known


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

    def __str__(self):
        return self.txid + '.' + str(self.n)


class SpentAnonOut:
    __slots__ = ('spent_type', 'spent_height', 'txid')

    def __init__(self, spent_type, spent_height, txid):
        self.spent_type = spent_type  # S for spent, 0 for a 0 output, SA for assumed spent
        self.spent_height = spent_height
        self.txid = txid


class AnonOutput:
    __slots__ = ('anonindex', 'pubkey', 'amount', 'blindingfactor')

    def __init__(self, anonindex, pubkey, amount, blindingfactor):
        self.anonindex = anonindex
        self.pubkey = pubkey
        self.amount = amount
        self.blindingfactor = blindingfactor


class ClaimedBlindedOutput:
    __slots__ = ('amount', 'spent_txid')

    def __init__(self, amount, spent_txid):
        self.amount = amount
        self.spent_txid = spent_txid

    def __str__(self):
        return str(self.amount) + ' ' + self.spent_txid


class ChainApp():
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

        self.exploit_fix_2_height = 976263
        self.last_frozen_anon_index = 27340
        self.num_post_fork_anon_txns = 0
        self.num_unfreeze_anon_txns = 0
        self.total_unfrozen_anon = 0

        self.num_post_fork_blind_txns = 0
        self.num_unfreeze_blind_txns = 0
        self.total_unfrozen_blind = 0
        self.unfrozen_ais = set()
        self.used_prevouts = set()
        self.txns_extra_mined = 0
        self.total_extra_mined = 0

        self.anonoutputs = []
        self.spent_aos = {}

        self.claimed_anon_outs = {}
        self.claimed_blind_outs = {}

        self.output_dir = settings.get('output_dir', '.')
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

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

        blockhash = self.callrpc('getblockhash', [height, ])
        block = self.callrpc('getblock', [blockhash])

        if self.totime > 0 and self.totime < block['time']:
            logging.info('Stopping before block {}, time {} > {}'.format(height, block['time'], self.totime))
            return False

        for txh in block['tx']:
            tx = self.callrpc('getrawtransaction', [txh, True])

            num_blinded_in = 0
            num_blinded_out = 0
            num_anon_in = 0
            num_anon_out = 0
            total_plain_in = 0
            total_plain_out = 0

            spends_post_fork = False
            spends_pre_fork = False
            rsi = []

            for txi_n, tx_input in enumerate(tx['vin']):
                #print('tx_input', json.dumps(tx_input, indent=4))
                if 'coinbase' in tx_input:
                    continue
                if 'type' in tx_input and tx_input['type'] == 'anon':
                    num_anon_in += 1

                    ring_members = []
                    for i in range(1000):
                        row = 'ring_row_{}'.format(i)
                        if row not in tx_input:
                            break
                        ring_members.append(tx_input[row])
                    rsi.append([tx_input['num_inputs'], tx_input['ring_size'], ring_members])
                    continue

                prev_tx = self.callrpc('getrawtransaction', [tx_input['txid'], True])
                prevout = prev_tx['vout'][tx_input['vout']]
                prevout_type = prevout['type']

                p = Prevout(tx_input['txid'], tx_input['vout'])
                if p in self.used_prevouts:
                    print('error: reused prevout ', p)
                self.used_prevouts.add(p)
                if p in self.claimed_blind_outs:
                    self.claimed_blind_outs[p].spent_txid = txh

                if prevout_type == 'blind':
                    print('prev_tx', json.dumps(prev_tx, indent=4))
                    num_blinded_in += 1

                    if prev_tx['height'] < self.exploit_fix_2_height:
                        spends_pre_fork = True
                    else:
                        spends_post_fork = True

            for tx_out in tx['vout']:
                tx_out_type = tx_out['type']
                if tx_out_type == 'anon':
                    num_anon_out += 1
                elif tx_out_type == 'blind':
                    num_blinded_out += 1
                elif tx_out_type == 'standard':
                    total_plain_out += tx_out['valueSat']

            if num_anon_in > 0:
                for ring in rsi:
                    print('ring_members', ring_members)
                    for ring_members in ring[2]:
                        ais = ring_members.split(',')
                        for ai in ais:
                            if int(ai) > self.last_frozen_anon_index:
                                spends_post_fork = True
                            else:
                                spends_pre_fork = True

                assert(not(spends_post_fork and spends_pre_fork))

                extra_mined = False
                if spends_pre_fork:
                    logging.info('unfreeze_anon_tx: {}, {}, height: {}'.format(txh, total_plain_out, height))
                    self.num_unfreeze_anon_txns += 1
                    self.total_unfrozen_anon += total_plain_out

                    anon_indexes = []
                    for ring in rsi:
                        for ring_members in ring[2]:
                            ais = ring_members.split(',')
                            for ai in ais:
                                if ai in self.unfrozen_ais:
                                    print('error: duplicate spend', ai)
                                    extra_mined = True
                                self.unfrozen_ais.add(ai)
                                anon_indexes.append(ai)

                    print('tx_prefork_anon', json.dumps(tx_input, indent=4))

                    if len(anon_indexes) != 1:
                        print('warning: len(anon_indexes) != 1,', len(anon_indexes))
                    else:
                        ct_fee = tx['vout'][0]['ct_fee']
                        ct_fee = int(decimal.Decimal(ct_fee) * decimal.Decimal(COIN))
                        anon_value = total_plain_out + ct_fee
                        anonoutput = self.callrpc('anonoutput', [anon_indexes[0]])
                        bv = '00' * 32
                        self.anonoutputs.append(AnonOutput(anon_indexes[0], anonoutput['publickey'], anon_value, bv))
                        self.spent_aos[anon_indexes[0]] = SpentAnonOut('S', height, txh)

                        if int(anon_indexes[0]) in self.claimed_anon_outs:
                            self.claimed_anon_outs[int(anon_indexes[0])].spent_txid = txh

                if extra_mined:
                    print('amount', total_plain_out)
                    self.txns_extra_mined += 1
                    self.total_extra_mined += total_plain_out

                if spends_post_fork:
                    #logging.info('post_fork_anon_tx: {}, {}'.format(txh, total_plain_out))
                    self.num_post_fork_anon_txns += 1

            if num_blinded_in > 0:
                print('num_blinded_in', num_blinded_in)
                assert(not(spends_post_fork and spends_pre_fork))
                if spends_pre_fork:
                    logging.info('unfreeze_blind_tx: {}, {}, height: {}'.format(txh, total_plain_out, height))
                    self.num_unfreeze_blind_txns += 1
                    self.total_unfrozen_blind += total_plain_out

                if spends_post_fork:
                    #logging.info('post_fork_anon_tx: {}, {}'.format(txh, total_plain_out))
                    self.num_post_fork_blind_txns += 1

        self.processed_height = height
        return True


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    if chain_app is not None:
        chain_app.stopRunning()


def printHelp():
    print('extract_anon_post_fork.py --outputdir=path --datadir=path --fromheight=x --totime=x')


def main():
    global chain_app
    settings = {
        'chain': 'mainnet',
        'fromheight': 976263,  # First block after exploit_fix_2_time, 1626109200, 2021-07-12 17:00:00 UTC
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

    chain_app = ChainApp(settings)
    chain_app.start()

    total_claimed_anon = 0
    total_claimed_blind = 0

    fork2_claims_file = os.path.expanduser('~/fork2_claims.csv')
    if os.path.exists(fork2_claims_file):

        with open(fork2_claims_file, 'r') as fp:
            for line in fp:
                line = line.strip()
                if line.startswith('#'):
                    continue
                split = line.split(',')
                amount = int(split[3])
                if split[2] == 'None':
                    total_claimed_blind += amount
                    chain_app.claimed_blind_outs[Prevout(split[0], split[1])] = ClaimedBlindedOutput(amount, '')
                    continue
                chain_app.claimed_anon_outs[int(split[2])] = ClaimedBlindedOutput(amount, '')
                total_claimed_anon += amount

    logging.info(f'claimed anon outs: {len(chain_app.claimed_anon_outs)}')
    logging.info(f'claimed blind outs: {len(chain_app.claimed_blind_outs)}')
    logging.info(f'total_claimed_anon: {total_claimed_anon}')
    logging.info(f'total_claimed_blind: {total_claimed_blind}')

    logging.info(f'Start height: {chain_app.processed_height}')

    try:
        r = chain_app.callrpc('getblockchaininfo')
        while r['blocks'] > chain_app.processed_height and chain_app.is_running:
            if not chain_app.processBlock(chain_app.processed_height + 1):
                break
    except Exception as ex:
        traceback.print_exc()

    logging.info(f'End height: {chain_app.processed_height}')

    logging.info(f'num_unfreeze_anon_txns: {chain_app.num_unfreeze_anon_txns}')
    logging.info(f'num_post_fork_anon_txns: {chain_app.num_post_fork_anon_txns}')
    logging.info(f'total_unfrozen_anon: {chain_app.total_unfrozen_anon}')

    logging.info(f'num_unfreeze_blind_txns: {chain_app.num_unfreeze_blind_txns}')
    logging.info(f'num_post_fork_blind_txns: {chain_app.num_post_fork_blind_txns}')
    logging.info(f'total_unfrozen_blind: {chain_app.total_unfrozen_blind}')

    logging.info(f'txns_extra_mined: {chain_app.txns_extra_mined}')
    logging.info(f'total_extra_mined: {chain_app.total_extra_mined}')

    with open(os.path.join(chain_app.output_dir, 'unfrozen_outputs.txt'), 'w') as fp:
        for ao in chain_app.anonoutputs:
            fp.write(f'{ao.anonindex},{ao.pubkey},{ao.amount},{ao.blindingfactor}\n')

        fp.write('Spends:\n')

        for ai, tx in chain_app.spent_aos.items():
            fp.write(f'{ai},{tx.spent_type},{tx.spent_height},{tx.txid}\n')

    claimed_blind_outs_spent = 0
    claimed_blind_spent_amount = 0
    for k, v in chain_app.claimed_blind_outs.items():
        logging.info(f'claimed_blind_outs: {k}, {v}')
        if v.spent_txid != '':
            claimed_blind_outs_spent += 1
            claimed_blind_spent_amount += v.amount
    claimed_anon_outs_spent = 0
    claimed_anon_spent_amount = 0
    for k, v in chain_app.claimed_anon_outs.items():
        logging.info(f'claimed_blind_outs: {k}, {v}')
        if v.spent_txid != '':
            claimed_anon_outs_spent += 1
            claimed_anon_spent_amount += v.amount

    logging.info(f'claimed_anon_outs_spent: {claimed_anon_outs_spent}')
    logging.info(f'claimed_anon_spent_amount: {claimed_anon_spent_amount}')
    logging.info(f'claimed_blind_outs_spent: {claimed_blind_outs_spent}')
    logging.info(f'claimed_blind_spent_amount: {claimed_blind_spent_amount}')

    logging.info(f'total_claimed_anon - claimed_anon_spent_amount: {total_claimed_anon - claimed_anon_spent_amount}')
    logging.info(f'total_claimed_blind - claimed_blind_spent_amount: {total_claimed_blind - claimed_blind_spent_amount}')

    print('Done.')


if __name__ == '__main__':
    main()
