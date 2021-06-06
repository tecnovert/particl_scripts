#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-0.19.2.11/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile

rm -r /tmp/anon_stats || true
mkdir -p /tmp/anon_stats
python anon_stats_sqlite.py -outputdir=/tmp/anon_stats -knowninfodir=~/known_wallets -totime=1614268800 > /tmp/anon_stats.txt

"""

__version__ = '0.4'

import os
import sys
import json
import time
import signal
import decimal
import logging
import sqlite3
import traceback

from util import (
    COIN,
    format8,
    open_rpc)


DEBUG = True
MAX_MONEY = 21000000 * COIN
chain_stats = None
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')
WITH_PLAIN_OUTPUTS = False

marked_addresses = ['Pjc3TqX23Mb23iw8RS2YuXjNX5s8fgficZ']


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


class SpentAnonOut:
    __slots__ = ('spent_type', 'spent_height', 'txid')

    def __init__(self, spent_type, spent_height, txid):
        self.spent_type = spent_type  # S for spent, 0 for a 0 output, SA for assumed spent
        self.spent_height = spent_height
        self.txid = txid


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
        self.debug = settings.get('chain', DEBUG)

        self.processed_height = settings.get('fromheight', 0)
        self.totime = settings.get('totime', 0)

        self.value_ctos = {}
        self.value_aos = {}
        self.spent_aos = {}
        self.unspent_aos = set()  # Outputs that are unspent at HF1 time
        self.source_aos = {}  # key anon_index, value source txid
        self.known_wallets = {}
        self.num_anon_txns = 0
        self.num_anon_outputs = 0
        self.num_mlsag_rows = 0

        self.sum_blind_added = 0
        self.sum_blind_removed = 0
        self.sum_anon_added = 0
        self.sum_anon_removed = 0

        self.ct_outputs = {}

        self.output_dir = settings.get('output_dir', '.')
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
        with open(os.path.join(self.output_dir, 'chain_stats.csv'), 'w') as fp:
            fp.write('height,txid,types,ct_fee,anon inputs,anon outputs,blinded inputs,blinded outputs,plain in,plain out,anon added,anon removed,blind added,blind removed, max possible blind in,sum anon added,sum anon removed,sum blind added,sum blind removed, sum anon+blind added, sum anon+blind removed\n')

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

        db_path = os.path.join(self.output_dir, 'chain_stats.db')
        if os.path.exists(db_path):
            os.remove(db_path)
        self.dbc = sqlite3.connect(db_path)

        c = self.dbc.cursor()
        c.execute('''CREATE TABLE blocks
                     (height INTEGER, blockhash TEXT, sum_anon_added INTEGER, sum_anon_removed INTEGER,
                      sum_blind_added INTEGER, sum_blind_removed INTEGER)''')

        c.execute('''CREATE TABLE transactions
                     (height INTEGER, txid TEXT, tx_type TEXT, ct_fee INTEGER,
                      plain_in INTEGER, plain_out INTEGER, anon_added INTEGER, anon_removed INTEGER,
                      blind_added INTEGER, blind_removed INTEGER, max_possible_blind_in INTEGER, bad_tx INTEGER)''')

        c.execute('''CREATE TABLE outputs
                     (txid TEXT, n INTEGER, type TEXT, anon_index INTEGER, value INTEGER, is_estimate INTEGER, spent_txid TEXT, is_spent_estimate INTEGER, has_anon_ancestor INTEGER, script TEXT, script_type TEXT, address TEXT, marked INTEGER)''')

        c.execute('''CREATE TABLE anon_inputs
                     (id INTEGER PRIMARY KEY, txid TEXT, n INTEGER, inputs INTEGER, ring_size INTEGER, prevouts TEXT, real_column INTEGER)''')

        c.execute('''CREATE TABLE anon_input_ring_members
                     (anon_input_id INTEGER, row INTEGER, column INTEGER, anon_index INTEGER)''')

        c.execute('''CREATE TABLE anon_out_estimate_adj
                     (anon_index INTEGER, txid TEXT, reduce_by INTEGER)''')

        self.dbc.commit()
        self.db_cursor = self.dbc.cursor()

    def __del__(self):
        if self.rpc_conn is not None:
            self.rpc_conn.close()
        self.dbc.commit()
        self.dbc.close()

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
            logging.info('num_anon_outputs, num_mlsag_rows: {}, {}'.format(self.num_anon_outputs, self.num_mlsag_rows))

            self.dbc.commit()
            self.db_cursor = self.dbc.cursor()

        blockhash = self.callrpc('getblockhash', [height, ])
        #logging.info('blockhash %s' % (blockhash))
        #block = self.callrpc('getblock', [blockhash, 3])
        block = self.callrpc('getblock', [blockhash])

        if self.totime > 0 and self.totime < block['time']:
            logging.info('Stopping before block {}, time {} > {}'.format(height, block['time'], self.totime))
            return False

        for txh in block['tx']:
            # TODO: Add ring_row_ to tx output in getblock
            tx = self.callrpc('getrawtransaction', [txh, True])
            #print('tx', json.dumps(tx, indent=4))

            num_blinded_in = 0
            num_blinded_out = 0
            num_anon_in = 0
            num_anon_out = 0
            total_plain_in = 0
            total_plain_out = 0

            has_tainted_blinded_input = False
            mark_anon_outputs = False

            tx_type = 'p->p'
            rsi = []
            new_anon_outputs = []
            new_blind_outputs = {}
            max_possible_blinded_value_in = 0  # TODO: reduce max when multiple blind inputs have the same txid and spend all outputs from there
            for txi_n, tx_input in enumerate(tx['vin']):
                #print('tx_input', json.dumps(tx_input, indent=4))
                if 'coinbase' in tx_input:
                    continue
                #if 'txid' in tx_input and tx_input['txid'] == '0000000000000000000000000000000000000000000000000000000000000000':
                #    continue  # Coinbase
                if 'type' in tx_input and tx_input['type'] == 'anon':
                    num_anon_in += 1

                    ring_members = []
                    ring_members_split = []
                    for i in range(1000):
                        row = 'ring_row_{}'.format(i)
                        if row not in tx_input:
                            break
                        ring_members.append(tx_input[row])
                        ais = tx_input[row].split(',')
                        for column, anon_index in enumerate(ais):
                            ring_members_split.append((i, column, anon_index))
                    rsi.append([tx_input['num_inputs'], tx_input['ring_size'], ring_members])

                    self.db_cursor.execute('INSERT INTO anon_inputs (txid, n, inputs, ring_size, prevouts)  VALUES (?, ?, ?, ?, ?)',
                                           (txh, txi_n, tx_input['num_inputs'], tx_input['ring_size'], '\n'.join(ring_members)))

                    anon_input_id = self.db_cursor.lastrowid
                    for ai in ring_members_split:
                        row, column, anon_index = ai
                        self.db_cursor.execute('INSERT INTO anon_input_ring_members (anon_input_id, row, column, anon_index)  VALUES (?, ?, ?, ?)',
                                               (anon_input_id, row, column, anon_index))

                    continue

                prev_tx = self.callrpc('getrawtransaction', [tx_input['txid'], True])
                #print('prev_tx', json.dumps(prev_tx, indent=4))
                prevout = prev_tx['vout'][tx_input['vout']]
                prevout_type = prevout['type']

                if prevout_type == 'blind':
                    num_blinded_in += 1
                    max_possible_blinded_value_in += self.ct_outputs[Prevout(tx_input['txid'], tx_input['vout'])].value

                    self.db_cursor.execute('UPDATE outputs SET spent_txid = ? WHERE txid = ? AND n = ?',
                                           (txh, tx_input['txid'], tx_input['vout']))

                    if has_tainted_blinded_input is False:
                        self.db_cursor.execute('SELECT has_anon_ancestor FROM outputs WHERE txid = ? AND n = ?',
                                               (tx_input['txid'], tx_input['vout']))
                        if self.db_cursor.fetchone()[0] > 0:
                            has_tainted_blinded_input = True

                elif prevout_type == 'standard':
                    total_plain_in += prevout['valueSat']
                    if WITH_PLAIN_OUTPUTS:
                        self.db_cursor.execute('UPDATE outputs SET spent_txid = ? WHERE txid = ? AND n = ?',
                                               (txh, tx_input['txid'], tx_input['vout']))

            for tx_out in tx['vout']:
                #print(tx_out)
                tx_out_type = tx_out['type']
                if tx_out_type == 'anon':
                    num_anon_out += 1
                    pubkey = tx_out['pubkey']

                    ao = self.callrpc('anonoutput', [pubkey])
                    new_anon_outputs.append((int(ao['index']), Prevout(txh, tx_out['n'])))
                    self.source_aos[int(ao['index'])] = txh
                elif tx_out_type == 'blind':
                    num_blinded_out += 1
                    new_blind_outputs[Prevout(txh, tx_out['n'])] = (tx_out['scriptPubKey']['hex'], tx_out['scriptPubKey']['type'], ' '.join(tx_out['scriptPubKey']['addresses']))
                elif tx_out_type == 'standard':
                    total_plain_out += tx_out['valueSat']
                    for addr in tx_out['scriptPubKey']['addresses']:
                        if addr in marked_addresses:
                            mark_anon_outputs = True
                    if WITH_PLAIN_OUTPUTS:
                        self.db_cursor.execute('INSERT INTO outputs (txid, n, type, value, script, script_type, address)  VALUES (?, ?, ?, ?, ?, ?, ?)',
                                               (txh, tx_out['n'], 'P', tx_out['valueSat'], tx_out['scriptPubKey']['hex'], tx_out['scriptPubKey']['type'], ' '.join(tx_out['scriptPubKey']['addresses'])))


            #print('total_plain_in', total_plain_in)
            #print('total_plain_out', total_plain_out)

            blind_removed = 0
            blind_added = 0
            anon_removed = 0
            anon_added = 0

            if num_blinded_in > 0:
                #print('Spending_blinded')
                if num_anon_out > 0 and total_plain_out == 0:
                    tx_type = 'b->a'
                elif num_blinded_out > 0 and total_plain_out == 0:
                    tx_type = 'b->b'
                else:
                    tx_type = 'b->p'

                ct_fee = tx['vout'][0]['ct_fee']
                ct_fee = int(decimal.Decimal(ct_fee) * decimal.Decimal(COIN))
                #print(ct_fee)
                #ct_fee = dquantize(ct_fee)

                #print('ct_fee', ct_fee)
                total_plain_out += ct_fee

                blind_removed = total_plain_out
            elif num_anon_in > 0:
                #print('Spending_anon')
                if num_blinded_out > 0 and total_plain_out == 0:
                    tx_type = 'a->b'
                elif num_anon_out > 0 and total_plain_out == 0:
                    tx_type = 'a->a'
                else:
                    tx_type = 'a->p'

                ct_fee = tx['vout'][0]['ct_fee']
                ct_fee = int(decimal.Decimal(ct_fee) * decimal.Decimal(COIN))
                #print(ct_fee)
                #ct_fee = dquantize(ct_fee)

                #print('ct_fee', ct_fee)
                total_plain_out += ct_fee

                anon_removed = total_plain_out

            if num_blinded_out > 0 and total_plain_in > 0:
                tx_type = 'p->b'
                ct_fee = int(decimal.Decimal(tx['vout'][0]['ct_fee']) * decimal.Decimal(COIN))
                blind_added = total_plain_in - (total_plain_out + ct_fee)

            elif num_anon_out > 0 and total_plain_in > 0:
                tx_type = 'p->a'
                ct_fee = int(decimal.Decimal(tx['vout'][0]['ct_fee']) * decimal.Decimal(COIN))
                anon_added = total_plain_in - (total_plain_out + ct_fee)

            self.sum_blind_added += blind_added
            self.sum_blind_removed += blind_removed
            self.sum_anon_added += anon_added
            self.sum_anon_removed += anon_removed

            max_anon_in_value_possible = 0
            # Each unknown anonoutput is estimated to be the maximum possible value at each txn
            #   if using multiple estimated outputs from the same txn, only use one for the new estimate
            used_anon_outs_from_txs = set()
            if len(rsi) > 0:
                try:
                    for inp in rsi:
                        cols = inp[1]
                        ringmember_rows = []
                        clear_columns = set()
                        sum_column_vals = [0] * cols
                        ai_matrix = []
                        for row in inp[2]:
                            ai_row = []
                            ais = row.split(',')
                            for column, anon_index in enumerate(ais):
                                ai = int(anon_index.strip())
                                ai_row.append(ai)
                                source_tx = self.source_aos[ai]
                                value_obj = chain_stats.value_aos[ai]
                                # TODO: needs adjustment for multi row anoninputs
                                if value_obj.known or source_tx not in used_anon_outs_from_txs:
                                    used_anon_outs_from_txs.add(source_tx)

                                    if ai not in self.unspent_aos and (ai not in self.spent_aos or self.spent_aos[ai].txid == txh):
                                        sum_column_vals[column] += value_obj.amount
                                    else:
                                        # Clear the whole column (for multi-row inputs), found
                                        # an input spent in a different tx, or
                                        # a known unspent input
                                        clear_columns.add(column)
                            ai_matrix.append(ai_row)

                        for c in clear_columns:
                            sum_column_vals[c] = 0

                        if len(clear_columns) >= cols - 1:
                            print('Only one possible column, assume spent', len(clear_columns), cols, clear_columns)
                            # Only one possible column, assume spent
                            for ai_row in ai_matrix:
                                for column, ai in enumerate(ai_row):
                                    if column in clear_columns:
                                        continue
                                    if ai in self.unspent_aos:
                                        print('Error: assuming known unspent is spent', ai, txh)
                                    elif ai in self.spent_aos:
                                        if self.spent_aos[ai].txid != txh:
                                            print('Error: assuming double-spend', ai, self.spent_aos[ai].txid, txh)
                                    else:
                                        self.spent_aos[ai] = SpentAnonOut('SA', height, txh)
                                        print('Adding spent ao', ai, txh)
                                        self.db_cursor.execute('UPDATE outputs SET spent_txid = ?, is_spent_estimate = 1 WHERE anon_index = ?',
                                                               (txh, ai))

                        #print('sum_column_vals', sum_column_vals)
                        max_anon_in_value_possible += max(sum_column_vals)
                except Exception as e:
                    print('Unable to estimate input value for', txh, str(e))
                #print('max_anon_in_value_possible', max_anon_in_value_possible)

            for bo, bod in new_blind_outputs.items():
                possible_value = 0
                is_known = False
                if bo in self.value_ctos:
                    possible_value = self.value_ctos[bo]
                    is_known = True
                else:
                    if max_possible_blinded_value_in > 0:
                        possible_value = max_possible_blinded_value_in - total_plain_out
                    elif max_anon_in_value_possible > 0:
                        possible_value = max_anon_in_value_possible - total_plain_out
                    else:
                        possible_value = blind_added

                if possible_value > MAX_MONEY:
                    possible_value = MAX_MONEY

                anon_tainted = 1 if num_anon_in > 0 or has_tainted_blinded_input else 0
                self.ct_outputs[bo] = CTOutput(possible_value, is_known)
                self.db_cursor.execute('INSERT INTO outputs (txid, n, type, value, has_anon_ancestor, is_estimate, script, script_type, address)  VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                       (bo.txid, bo.n, 'B', possible_value, anon_tainted, 0 if is_known else 1, bod[0], bod[1], bod[2]))

            bad_tx = False
            if max_possible_blinded_value_in < blind_removed:
                print('max_possible_blinded_value_in < blind_removed', txh, max_possible_blinded_value_in, blind_removed)
                bad_tx = True
            if max_anon_in_value_possible < anon_removed:
                print('max_anon_in_value_possible < anon_removed', txh, max_anon_in_value_possible, anon_removed)
                bad_tx = True

            if num_blinded_in > 0 or num_blinded_out > 0 or num_anon_in > 0 or num_anon_out > 0:
                ct_fee = int(decimal.Decimal(tx['vout'][0]['ct_fee']) * decimal.Decimal(COIN))

                self.db_cursor.execute('''INSERT INTO transactions (
                                          height, txid, tx_type, ct_fee,
                                          plain_in, plain_out, anon_added, anon_removed,
                                          blind_added, blind_removed, max_possible_blind_in, bad_tx) VALUES (
                                          ?, ?, ?, ?,
                                          ?, ?, ?, ?,
                                          ?, ?, ?, ?)''',
                                       (height, txh, tx_type, ct_fee,
                                        total_plain_in, total_plain_out, anon_added, anon_removed,
                                        blind_added, blind_removed, max_possible_blinded_value_in, 1 if bad_tx else 0))

                with open(os.path.join(self.output_dir, 'chain_stats.csv'), 'a') as fp:
                    fp.write('%d,%s,%s,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d,%d\n'
                             % (height,
                                txh,
                                tx_type,
                                ct_fee,
                                num_anon_in,
                                num_anon_out,
                                num_blinded_in,
                                num_blinded_out,
                                total_plain_in,
                                total_plain_out,
                                anon_added,
                                anon_removed,
                                blind_added,
                                blind_removed,
                                max_possible_blinded_value_in,
                                self.sum_anon_added,
                                self.sum_anon_removed,
                                self.sum_blind_added,
                                self.sum_blind_removed,
                                self.sum_anon_added + self.sum_blind_added,
                                self.sum_anon_removed + self.sum_blind_removed))

                    if num_anon_in > 0 or anon_removed > 0 or anon_added > 0:
                        self.num_anon_txns += 1
                        for wk, wd in self.known_wallets.items():
                            if txh in wd['txids']:
                                fp.write('known tx,%s\n' % (wk))
                                break

                    if len(new_anon_outputs) > 0:
                        #fp.write('new aos,%s \n' % (' '.join(str(x) for x in new_anon_outputs)))

                        max_value = 0
                        if total_plain_in > 0:
                            max_value = (anon_added - anon_removed)
                        elif max_possible_blinded_value_in > 0:
                            max_value = max_possible_blinded_value_in - total_plain_out
                        else:
                            max_value = max_anon_in_value_possible - total_plain_out

                        if max_value > MAX_MONEY:
                            max_value = MAX_MONEY

                        if max_value < 0:
                            max_value = 0

                        display = []
                        for nao in new_anon_outputs:
                            self.num_anon_outputs += 1
                            known = False

                            spent_in_tx = None
                            if nao[0] in self.spent_aos:
                                spent_in_tx = self.spent_aos[nao[0]].txid
                            if nao[0] in self.value_aos:
                                aov = self.value_aos[nao[0]]
                                ao_max_val = aov.amount
                                known = aov.known
                            else:
                                ao_max_val = max_value
                                chain_stats.value_aos[nao[0]] = AnonOutValue(ao_max_val, False)
                            self.db_cursor.execute('INSERT INTO outputs (txid, n, type, anon_index, value, is_estimate, spent_txid, marked)  VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                                   (nao[1].txid, nao[1].n, 'A', nao[0], ao_max_val, 0 if known else 1, spent_in_tx, 1 if mark_anon_outputs else 0))

                            display.append('{} [{}{}]'.format(nao[0], '' if known else '<', ao_max_val))

                        fp.write('new aos,%s \n' % (' '.join(display)))

                    if len(rsi) > 0:
                        for inp in rsi:
                            ringmember_rows = []
                            for row in inp[2]:
                                self.num_mlsag_rows += 1
                                new_row = []
                                ais = row.split(',')
                                for anon_index in ais:
                                    ai = int(anon_index.strip())

                                    is_spent = False
                                    if ai in self.spent_aos and self.spent_aos[ai].spent_height < height:
                                        is_spent = True
                                    if ai in self.value_aos:
                                        aov = self.value_aos[ai]
                                        new_row.append('{}{}[{}{}]'.format(ai, 'S' if is_spent else '_', '' if aov.known else '<', aov.amount))
                                    else:
                                        new_row.append('{}{}'.format(ai, 'S' if is_spent else '_',))
                                ringmember_rows.append(' '.join(new_row))

                            ringmembers = '"(' + '),\n('.join(ringmember_rows) + ')"'
                            fp.write('"%d,%d",%s\n' % (int(inp[0]), int(inp[1]), ringmembers))

        self.db_cursor.execute('INSERT INTO blocks (height, blockhash, sum_anon_added, sum_anon_removed, sum_blind_added, sum_blind_removed)  VALUES (?, ?, ?, ?, ?, ?)',
                               (height, blockhash, self.sum_anon_added, self.sum_anon_removed, self.sum_blind_added, self.sum_blind_removed))

        self.processed_height = height
        return True


def signal_handler(sig, frame):
    print('signal %d detected, ending program.' % (sig))
    if chain_stats is not None:
        chain_stats.stopRunning()


def printHelp():
    print('anon_stats.py --outputdir=path --datadir=path --knowninfodir=path --fromheight=x --totime=x')


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
            if name == 'knowninfodir':
                settings['knowninfodir'] = os.path.expanduser(s[1])
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

    chain_stats = ChainTracker(settings)
    chain_stats.start()

    duplicate_aov = 0
    duplicate_aos = 0
    duplicate_aous = 0
    duplicate_ctov = 0
    zero_value_aos = 0
    zero_value_ctos = 0
    if 'knowninfodir' in settings:
        knowninfodir = settings['knowninfodir']
        files = os.listdir(knowninfodir)
        for f in files:
            known_txids = []
            known_aos = {}

            ctv_section = False
            spend_section = False
            with open(os.path.join(knowninfodir, f)) as fpw:
                for line in fpw:
                    line = line.strip()
                    if line.startswith('#'):
                        continue
                    if line == 'Spends:':
                        spend_section = True
                        ctv_section = False
                        continue
                    if line == 'CT values:':
                        ctv_section = True
                        spend_section = False
                        continue
                    if line == 'Anon values:':
                        ctv_section = False
                        spend_section = False
                        continue
                    if line == 'Transaction ids:':
                        ctv_section = False
                        spend_section = False
                        continue
                    split = line.split(',')

                    if f == 'spent.txt' or spend_section is True:
                        if len(split) == 4:
                            aoi = int(split[0])
                            if aoi in chain_stats.spent_aos:
                                #logging.info('Duplicate aos: {}'.format(aoi))
                                duplicate_aos += 1
                                continue
                            chain_stats.spent_aos[aoi] = SpentAnonOut(split[1], int(split[2]), split[3])
                        elif len(split) == 2:
                            aoi = int(split[0])
                            if split[1] != 'U':
                                logging.info('Warning unknown unspent aos format: {}'.format(line))
                                continue
                            if aoi in chain_stats.unspent_aos:
                                #logging.info('Duplicate aos: {}'.format(aoi))
                                duplicate_aous += 1
                                continue
                            chain_stats.unspent_aos.add(aoi)
                        continue

                    if ctv_section is True:
                        if len(split) == 4:
                            txid = split[0]
                            vout = int(split[1])
                            ctv = int(split[2])
                            if Prevout(txid, vout) in chain_stats.value_ctos:
                                #logging.info('Duplicate ctv: {}, {}'.format(txid, vout))
                                duplicate_ctov += 1
                                continue

                            source_tx = chain_stats.callrpc('getrawtransaction', [txid, True])
                            value_commitment = source_tx['vout'][vout]['valueCommitment']
                            try:
                                verify_rv = chain_stats.callrpc('verifycommitment', [value_commitment, split[3], format8(ctv)])
                            except Exception as e:
                                print('verifycommitment failed', txid, vout, value_commitment, split[3], format8(ctv))
                                continue
                            assert(verify_rv['result'] is True)
                            chain_stats.value_ctos[Prevout(txid, vout)] = ctv
                            if ctv == 0:
                                zero_value_ctos += 1
                        continue

                    if len(line) == 64:
                        known_txids.append(line)
                        continue
                    if len(split) >= 3:
                        aoi = int(split[0])
                        aov = int(split[2])
                        known_aos[aoi] = aov

                        if len(split) == 3:
                            pass
                            logging.info('Warning value_aos with missing blinding factor from: {}'.format(f))
                            #logging.info('Skipping value_aos with missing blinding factor from: {}'.format(f))
                            #continue
                        else:
                            # Verify commitment
                            ao_rv = chain_stats.callrpc('anonoutput', [str(aoi)])
                            txid = ao_rv['txnhash']
                            vout = int(ao_rv['n'])
                            source_tx = chain_stats.callrpc('getrawtransaction', [txid, True])

                            value_commitment = source_tx['vout'][vout]['valueCommitment']
                            if split[3] == '0000000000000000000000000000000000000000000000000000000000000000':
                                logging.info('Warning value_aos with null blinding factor from: {}'.format(f))
                            else:
                                try:
                                    verify_rv = chain_stats.callrpc('verifycommitment', [value_commitment, split[3], format8(aov)])
                                except Exception as e:
                                    logging.info('verifycommitment failed {}, {}, {}'.format(value_commitment, split[3], format8(aov)))
                                    raise(e)
                                assert(verify_rv['result'] is True)

                        if aoi in chain_stats.value_aos:
                            #logging.info('Duplicate aov: {}'.format(aoi))
                            duplicate_aov += 1
                            continue
                        chain_stats.value_aos[aoi] = AnonOutValue(aov, True)
                        if aov == 0:
                            zero_value_aos += 1

            if len(known_txids) > 0 or len(known_aos) > 0:
                chain_stats.known_wallets[f] = {'txids': known_txids, 'aos': known_aos}

    logging.info('value_aos             {}'.format(len(chain_stats.value_aos)))
    logging.info('spent_aos             {}'.format(len(chain_stats.spent_aos)))
    logging.info('unspent_aos           {}'.format(len(chain_stats.unspent_aos)))
    logging.info('value_ctos            {}'.format(len(chain_stats.value_ctos)))

    logging.info('duplicate value_aos   {}'.format(duplicate_aov))
    logging.info('duplicate spent_aos   {}'.format(duplicate_aos))
    logging.info('duplicate value_ctos  {}'.format(duplicate_ctov))

    logging.info('zero_value_aos        {}'.format(zero_value_aos))
    logging.info('zero_value_ctos       {}'.format(zero_value_ctos))

    try:
        r = chain_stats.callrpc('getblockchaininfo')
        while r['blocks'] > chain_stats.processed_height and chain_stats.is_running:
            if not chain_stats.processBlock(chain_stats.processed_height + 1):
                break
    except Exception as ex:
        traceback.print_exc()

    logging.info('num_anon_txns     {}'.format(chain_stats.num_anon_txns))
    logging.info('num_anon_outputs  {}'.format(chain_stats.num_anon_outputs))
    logging.info('num_mlsag_rows    {}'.format(chain_stats.num_mlsag_rows))

    # Compile blacklisted anon outputs
    q = chain_stats.db_cursor.execute('''SELECT outputs.anon_index, outputs.txid FROM outputs, transactions
                                         WHERE outputs.txid = transactions.txid AND transactions.bad_tx = 1''')

    logging.info('Blacklisted anon indices:')
    for row in q:
        logging.info('{}, {}'.format(row[0], row[1]))

    print('Done.')


if __name__ == '__main__':
    main()
