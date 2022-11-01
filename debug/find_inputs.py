#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""
$ export BIN_PATH=~/tmp/particl-0.21.2.11/bin
$ ${BIN_PATH}/particl-qt -server
$ python find_inputs.py datadir addr


TODO: graphs

"""

import os
import sys
import json
import time
import sqlite3
from util import callrpc, format8


class FindAddress():
    def __init__(self, address, dist_from_main):
        self.address = address

        self.txids_vout = set()
        self.dist_from_main = dist_from_main


class InputTxn():
    def __init__(self, tx, height, blockhash):
        self.tx = tx
        self.height = height
        self.blockhash = blockhash


class AddressInput():
    def __init__(self, address, amount):
        self.address = address
        self.amount = amount
        self.num_txns = 0
        self.min_height = -1
        self.max_height = -1

    def updateHeights(self, height):
        if self.min_height == -1 or height < self.min_height:
            self.min_height = height
        if height > self.max_height:
            self.max_height = height
        self.num_txns += 1


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


addrs = {}
txns = {}
linked_prevouts = set()


def make_rpc_func(rpc_port, rpc_auth, wallet=None):
    rpc_port = rpc_port
    rpc_auth = rpc_auth
    wallet = wallet

    def rpc_func(cmd, args=[], wallet_override=None):
        nonlocal rpc_port, rpc_auth, wallet
        return callrpc(rpc_port, rpc_auth, cmd, args, wallet if wallet_override is None else wallet_override)
    return rpc_func


def main():
    particl_data_dir = os.path.expanduser(sys.argv[1])
    main_address = os.path.expanduser(sys.argv[2])

    max_dist_from_main = 3

    # db_filepath = '/tmp/find_inputs.sqlite'
    db_filepath = 'find_inputs.sqlite'

    chain = 'mainnet'

    authcookiepath = os.path.join(particl_data_dir, '' if chain == 'mainnet' else chain, '.cookie')
    for i in range(10):
        if not os.path.exists(authcookiepath):
            time.sleep(0.5)
    with open(authcookiepath) as fp:
        rpc_auth = fp.read()

    rpc_port = 51735 if chain == 'mainnet' else 51935

    callrpcw = make_rpc_func(rpc_port, rpc_auth)

    r = callrpcw('getnetworkinfo')
    print('Core version', r['version'])

    block_hash = callrpcw('getbestblockhash')

    '''
    height_from = 100000
    block_hash = callrpcw('getblockhash', [height_from,])
    '''
    print('Results from block', block_hash)
    print('max_dist_from_main', max_dist_from_main)

    dbc = sqlite3.connect(db_filepath)
    c = dbc.cursor()
    c.execute('''CREATE TABLE outputs
                 (txid TEXT, n INTEGER, type TEXT, anon_index INTEGER, value INTEGER, is_coinbase INTEGER, spent_txid TEXT, script TEXT, script_type TEXT, address TEXT)''')
    dbc.commit()

    addrs[main_address] = FindAddress(main_address, 0)

    # List of addreses in the (reverse) order they appear in the chain
    addrs_seen = []
    prevouts_skipped = 0

    while True:
        block_data = callrpcw('getblock', [block_hash, 2])

        block_height = block_data['height']
        for tx_i, tx in enumerate(block_data['tx']):
            txid = tx['txid']
            for tx_out in tx['vout']:

                min_dist_from_main = 1000
                found_addresses = []
                try:
                    if tx_out['type'] != 'standard':
                        continue
                    for k, addr_v in addrs.items():
                        if 'addresses' not in tx_out['scriptPubKey']:
                            # "asm": "OP_RETURN",
                            # prefork workaround for smsg/mp data output limits was to add an empty opreturn output
                            continue
                        if k in tx_out['scriptPubKey']['addresses']:
                            # Filter out prevouts that don't feed into the main address
                            if addr_v.dist_from_main > 0:
                                if Prevout(txid, tx_out['n']) not in linked_prevouts:
                                    prevouts_skipped += 1
                                    continue

                            if addr_v.dist_from_main < min_dist_from_main:
                                min_dist_from_main = addr_v.dist_from_main

                            found_addresses.append(k)

                except Exception as e:
                    print('error tx_out', e)
                    print('tx', json.dumps(tx, indent=4))

                if min_dist_from_main >= max_dist_from_main:
                    continue

                if len(found_addresses) == 0:
                    continue

                for k in found_addresses:
                    if k not in addrs_seen:
                        addrs_seen.append(k)
                    addr_v = addrs[k]
                    addr_v.txids_vout.add(txid)

                txns[txid] = InputTxn(tx, block_height, block_hash)

                for txi_n, tx_input in enumerate(tx['vin']):
                    if 'coinbase' in tx_input:
                        break
                    if 'type' in tx_input and tx_input['type'] == 'anon':
                        continue

                    prev_txid = tx_input['txid']
                    prev_tx = callrpcw('getrawtransaction', [prev_txid, True])
                    if prev_txid not in txns:
                        txns[prev_txid] = InputTxn(prev_tx, prev_tx['height'], prev_tx['blockhash'])
                    linked_prevouts.add(Prevout(prev_txid, tx_input['vout']))
                    prevout = prev_tx['vout'][tx_input['vout']]

                    for addr in prevout['scriptPubKey']['addresses']:
                        if addr not in addrs:
                            addrs[addr] = FindAddress(addr, min_dist_from_main + 1)

        if block_data['height'] % 10000 == 0:
            print('height', block_data['height'], flush=True)
            print('len(txns)', len(txns))

        try:
            block_hash = block_data['previousblockhash']
        except Exception as e:
            print('previousblockhash', e)
            break

    print('linked_prevouts', len(linked_prevouts))  # prevouts mapped to main_address
    print('prevouts_skipped', prevouts_skipped)  # prevouts of addresses linked to main_address not connected in the txout history
    print('len(txns)', len(txns))

    total_coinbase_amount = 0
    for addr in addrs_seen:
        print('\n\n------------------------------------------------------------')
        print('    ', addr)
        print('------------------------------------------------------------\n')

        plain_addrs_from = {}
        blind_addrs_from = {}

        anon_inputs = AddressInput('anon', 0)
        coinbase_inputs = AddressInput('coinbase', 0)
        anon_input_txids = []

        addr_info = addrs[addr]

        print('dist from main', addr_info.dist_from_main)

        c = dbc.cursor()

        for txid in addr_info.txids_vout:
            tx_obj = txns[txid]
            tx = tx_obj.tx
            tx_height = tx_obj.height
            num_anon_inputs = 0

            for txi_n, tx_input in enumerate(tx['vin']):
                if 'coinbase' in tx_input:
                    coinbase_inputs.updateHeights(tx_height)
                    for txo in tx['vout']:
                        try:
                            if addr in txo['scriptPubKey']['addresses']:
                                coinbase_inputs.amount += txo['valueSat']

                                c.execute('INSERT INTO outputs (txid, n, type, value, script, script_type, address, is_coinbase)  VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                                          (txid, txo['n'], 'P', txo['valueSat'], txo['scriptPubKey']['hex'], txo['scriptPubKey']['type'], ' '.join(txo['scriptPubKey']['addresses']), 1))

                        except Exception as e:
                            print('error tx vout', e)
                            print('tx', json.dumps(tx, indent=4))

                    break
                if 'type' in tx_input and tx_input['type'] == 'anon':
                    num_anon_inputs += 1
                    anon_input_txids.append(Prevout(txid, txi_n))
                    anon_inputs.updateHeights(tx_height)
                    continue

                prev_tx_obj = txns[tx_input['txid']]
                prev_tx = prev_tx_obj.tx

                prevout = prev_tx['vout'][tx_input['vout']]

                try:
                    update_addrs_plain = set()
                    update_addrs_blind = set()
                    if prevout['type'] == 'blind':
                        for addr in prevout['scriptPubKey']['addresses']:
                            if addr not in blind_addrs_from:
                                blind_addrs_from[addr] = AddressInput(addr, 0)
                            update_addrs_blind.add(addr)
                    elif tx_out['type'] == 'anon':
                        raise ValueError('Shouldn\'t happen')
                    else:
                        for addr in prevout['scriptPubKey']['addresses']:
                            if addr not in plain_addrs_from:
                                plain_addrs_from[addr] = AddressInput(addr, prevout['valueSat'])
                            else:
                                plain_addrs_from[addr].amount += prevout['valueSat']
                            update_addrs_plain.add(addr)

                    for addr in update_addrs_plain:
                        if addr in plain_addrs_from:
                            plain_addrs_from[addr].updateHeights(tx_height)
                    for addr in update_addrs_blind:
                        if addr in blind_addrs_from:
                            blind_addrs_from[addr].updateHeights(tx_height)

                except Exception as e:
                    print('error format output', e)
                    print('txid source', txid)
                    print('txid input', tx_input['txid'])
                    print('vout input', tx_input['vout'])
                    print('prev_tx', json.dumps(prev_tx, indent=4))

        print('num_anon_inputs', num_anon_inputs)
        print('num_blind_inputs', len(blind_addrs_from))
        print('num_plain_inputs', len(plain_addrs_from))
        print('\nplain_addrs_from')

        output_fmt = '{:54}{:<12}{:<12}{:<12}{:>12}'
        print(output_fmt.format('Address', 'Num Txns', 'Min Height', 'Max Height', 'Amount'))
        for addr, obj in plain_addrs_from.items():
            print(output_fmt.format(addr, obj.num_txns, obj.min_height, obj.max_height, format8(obj.amount)))

        if len(blind_addrs_from) > 0:
            print('\nblind_addrs_from')
            print(output_fmt.format('Address', 'Num Txns', 'Min Height', 'Max Height', 'Amount'))
            for addr, obj in blind_addrs_from.items():
                print(output_fmt.format(addr, obj.num_txns, obj.min_height, obj.max_height, ''))

        if anon_inputs.num_txns > 0:
            print('\nanon inputs')
            print(output_fmt.format('anon', anon_inputs.num_txns, anon_inputs.min_height, anon_inputs.max_height, ''))

            for prevout in anon_input_txids:
                print(prevout.txid, prevout.n)

        if coinbase_inputs.num_txns > 0:
            print('\ncoinbase inputs')
            print(output_fmt.format('coinbase', coinbase_inputs.num_txns, coinbase_inputs.min_height, coinbase_inputs.max_height, format8(coinbase_inputs.amount)))
            total_coinbase_amount += coinbase_inputs.amount

        dbc.commit()

    print('total_coinbase_amount', format8(total_coinbase_amount))

    dbc.close()


if __name__ == '__main__':
    main()
