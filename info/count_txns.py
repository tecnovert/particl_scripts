#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""
Count txns per day by type.
A transaction is counted as blind or anon if it has atleast one nonstandard output or input.
A standard output has only standard outputs and inputs.

$ export BIN_PATH=~/tmp/particl-0.21.2.7/bin
$ ${BIN_PATH}/particl-qt -server -txindex=1 -testnet
$ python count_txns.py --days=14 --network=testnet

"""

__version__ = '0.1'

import os
import json
import time
import shlex
import argparse
import threading
import subprocess


bin_path = os.path.join(os.path.expanduser(os.getenv('BIN_PATH', '')), 'particl-cli')


def callrpc(cmd, datadir=None, network=None, wallet=None):
    args = [bin_path, ]

    if datadir:
        args += ['--datadir=' + datadir, ]
    if network and network != 'mainnet':
        args += ['--' + network, ]
    if wallet:
        args += ['--rpcwallet=' + wallet, ]
    args += shlex.split(cmd)

    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out = p.communicate()

    if len(out[1]) > 0:
        raise ValueError(out[1])

    return out[0]


def make_rpc_func(datadir, network, wallet=None):
    datadir = datadir
    network = network
    wallet = wallet

    def rpc_func(cmd, wallet_override=None):
        nonlocal network, datadir, wallet
        return callrpc(cmd, datadir, network, wallet if wallet_override is None else wallet_override)
    return rpc_func


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))
    parser.add_argument('--network', dest='network', default='')
    parser.add_argument('--datadir', dest='datadir', help='Particl datadir (default=~/.particl)', default='~/.particl', required=False)
    parser.add_argument('--days', dest='days', help='Number of days to count back', type=int, default=7, required=False)
    parser.add_argument('--starthash', dest='starthash', help='Block hash to start from', default='', required=False)
    args = parser.parse_args()

    args.datadir = os.path.expanduser(args.datadir)

    print('network', 'mainnet' if args.network == '' else args.network)

    callrpc = make_rpc_func(args.datadir, args.network)

    delay_event = threading.Event()

    if args.starthash == '':
        block_hash = callrpc('getbestblockhash').strip().decode('utf8')
    else:
        block_hash = args.starthash

    print('Results from block', block_hash)

    total_txns = 0
    day_txns = 0

    total_cs_txns = 0
    day_cs_txns = 0

    total_s_txns = 0
    day_s_txns = 0

    total_a_txns = 0
    day_a_txns = 0

    total_b_txns = 0
    day_b_txns = 0

    days = {}

    num_days = 0
    last_date = ''

    while True:
        block_data = json.loads(callrpc(f'getblock {block_hash} 2'))

        date = time.strftime('%Y-%m-%d', time.gmtime(int(block_data['time'])))
        if last_date != '' and date != last_date:
            num_days += 1
            days[last_date] = (day_txns, day_cs_txns, day_s_txns, day_a_txns, day_b_txns)
            day_txns = 0
            day_cs_txns = 0
            day_s_txns = 0
            day_a_txns = 0
            day_b_txns = 0
        last_date = date

        if num_days >= args.days:
            break

        for tx_i, tx in enumerate(block_data['tx']):
            day_txns += 1
            total_txns += 1

            if total_txns % 100:
                print('txns', total_txns, ', day', num_days, end='\r')

            num_anon_in = 0
            num_blind_in = 0
            num_standard_in = 0

            num_anon_out = 0
            num_blind_out = 0
            num_standard_out = 0

            if tx['version'] == 672 and tx_i == 0:
                day_cs_txns += 1
                total_cs_txns += 1
                continue

            for txi_n, tx_input in enumerate(tx['vin']):
                if 'coinbase' in tx_input:
                    break
                if 'type' in tx_input and tx_input['type'] == 'anon':
                    num_anon_in += 1
                    continue

                prev_tx = json.loads(callrpc('getrawtransaction {} true'.format(tx_input['txid'])))
                prevout = prev_tx['vout'][tx_input['vout']]
                prevout_type = prevout['type']

                if prevout_type == 'blind':
                    num_blind_in += 1
                else:
                    num_standard_in += 1

            for tx_out in tx['vout']:
                tx_out_type = tx_out['type']
                if tx_out_type == 'anon':
                    num_anon_out += 1
                elif tx_out_type == 'blind':
                    num_blind_out += 1
                elif tx_out_type == 'standard':
                    num_standard_out += 1

            if num_blind_out + num_blind_in > 0:
                day_b_txns += 1
                total_b_txns += 1

            if num_anon_out + num_anon_in > 0:
                day_a_txns += 1
                total_a_txns += 1

            if num_blind_out + num_blind_in + num_anon_out + num_anon_in == 0:
                day_s_txns += 1
                total_s_txns += 1

        block_hash = block_data['previousblockhash']

    output_fmt = '{:12}{:>12}{:>12}{:>12}{:>12}{:>12}'
    print(output_fmt.format('Date', 'All', 'Coinstake', 'Standard', 'Anon', 'Blind'))
    for k, v in days.items():
        print(output_fmt.format(k, v[0], v[1], v[2], v[3], v[4]))

    print('')
    print(output_fmt.format('Totals', total_txns, total_cs_txns, total_s_txns, total_a_txns, total_b_txns))

    print('Done.')


if __name__ == '__main__':
    main()
