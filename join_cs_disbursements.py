#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (c) 2020-2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE or http://www.opensource.org/licenses/mit-license.php.

"""
Collect coldstaking disbursements in larger outputs

$ export BIN_PATH=~/tmp/particl-0.21.2.7/bin
$ ${BIN_PATH}/particl-qt -server -testnet
$ python join_cs_disbursements.py --network=testnet --wallet=main_testnet_wallet.dat
"""

__version__ = '0.2'

import os
import json
import shlex
import random
import decimal
import argparse
import threading
import subprocess


bin_path = os.path.join(os.path.expanduser(os.getenv('BIN_PATH', '')), 'particl-cli')
decimal.getcontext().prec = 16
COIN = 100000000


low_filter = 100.0
high_filter = 2000.0


class SkipIteration(Exception):
    pass


class NoneOutstanding(Exception):
    pass


def dquantize(n, places=8):
    return n.quantize(decimal.Decimal(10) ** -places)


def callrpc(cmd, network='', wallet=''):
    args = [bin_path, ]

    if network:
        args += ['--' + network, ]
    if wallet:
        args += ['--rpcwallet=' + wallet, ]
    args += shlex.split(cmd)

    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out = p.communicate()

    if len(out[1]) > 0:
        raise ValueError(out[1])

    return out[0]


def get_sendcmd(data, ignore_set, args):
    by_address = {}
    total_by_address = {}

    for utxo in data:
        if args.testonly:
            outputid = utxo['txid'] + ',' + str(utxo['vout'])
            if outputid in ignore_set:
                continue
        utxo_list = by_address.get(utxo['address'], [])
        utxo_list.append(utxo)
        by_address[utxo['address']] = utxo_list

        total = total_by_address.get(utxo['address'], [0, 0])
        total[0] += 1
        total[1] += utxo['amount']
        total_by_address[utxo['address']] = total

    cmd = 'sendtypeto part part "['
    for addr, data in by_address.items():
        print('\nAddress ', addr)
        by_amount = sorted(data, key=lambda x: x['amount'])
        totals = total_by_address[addr]
        print(totals[0], totals[1])
        print(len(data))

        while True:
            # From the lowest amount, find the first utxo < cutoff_amount
            last_i = None
            last_utxo = None
            for i, utxo in enumerate(by_amount):
                if utxo['amount'] < low_filter:
                    continue
                if utxo['amount'] >= high_filter:
                    continue
                if 'coldstaking_address' not in utxo:
                    continue
                last_i = i
                last_utxo = utxo
                break
            print(last_i, last_utxo)

            if last_i is None:
                break
            del by_amount[last_i]

            total_out = decimal.Decimal(0)
            to_join = []
            for i in range(len(by_amount)):
                utxo = by_amount[0]
                if utxo['amount'] >= low_filter:
                    break
                to_join.append(utxo)
                total_out += decimal.Decimal(utxo['amount'] * COIN)
                del by_amount[0]

                if len(to_join) >= args.inputlimit:
                    break

            if len(to_join) < 1:
                break

            total_out += decimal.Decimal(last_utxo['amount'] * COIN)
            print('total_out', total_out)
            cmd = 'sendtypeto part part "['
            script_to = last_utxo['scriptPubKey']
            cmd += '{\\"address\\":\\"script\\",\\"script\\":\\"' + script_to + '\\",\\"amount\\":' + str(dquantize(total_out / COIN)) + ',\\"subfee\\":true}]" '
            cmd += '\\"\\" '    # comment
            cmd += '\\"\\" '    # comment_to
            cmd += '5 '         # ringsize
            cmd += '1 '         # inputs_per_sig
            if args.includewatchonly:
                cmd += 'true '     # test_fee
            else:
                cmd += 'false '     # test_fee
            cmd += '"{\\"inputs\\":['
            cmd += '{\\"tx\\":\\"' + last_utxo['txid'] + '\\",\\"n\\":' + str(last_utxo['vout']) + '}'
            for utxo in to_join:
                cmd += ',{\\"tx\\":\\"' + utxo['txid'] + '\\",\\"n\\":' + str(utxo['vout']) + '}'

            cmd += ']'
            if args.includewatchonly:
                cmd += ',\\"show_hex\\":true'
                cmd += ',\\"includeWatching\\":true'
            cmd += '}"'
            if args.testonly:
                ignore_set.add(last_utxo['txid'] + ',' + str(last_utxo['vout']))
                for utxo in to_join:
                    ignore_set.add(utxo['txid'] + ',' + str(utxo['vout']))

            return cmd
    raise NoneOutstanding


def make_boolean(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('true', '1'):
        return True
    if v.lower() in ('false', '0'):
        return False
    raise argparse.ArgumentTypeError('Boolean value expected.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))
    parser.add_argument('--network', dest='network', default='')
    parser.add_argument('--wallet', dest='wallet', default='')
    parser.add_argument('--minwait', dest='minwait', help='Minimum number of seconds to wait before repeating [1, 3600] (default=60)', type=int, default=60, required=False)
    parser.add_argument('--maxwait', dest='maxwait', help='Maximum number of seconds to wait before repeating [1, 7200] (default=600)', type=int, default=600, required=False)
    parser.add_argument('--testonly', dest='testonly', help='If true sendtypeto command will not be run on daemon (default=false)', type=make_boolean, default=False, required=False)
    parser.add_argument('--includewatchonly', dest='includewatchonly', help='Construct sendtypeto command with "includeWatching" set (default=false)', type=make_boolean, default=False, required=False)
    parser.add_argument('--minblockdiff', dest='minblockdiff', help='Minimum number of blocks to wait before repeating [0, 600] (default=1)', type=int, default=1, required=False)
    parser.add_argument('--inputlimit', dest='inputlimit', help='Maximum number of outputs to join per transaction [1, 600] (default=60)', type=int, default=60, required=False)
    args = parser.parse_args()

    if args.minwait < 1 or args.minwait > 3600:
        raise argparse.ArgumentTypeError('Invalid minwait')
    if args.maxwait < args.minwait or args.maxwait > 7200:
        raise argparse.ArgumentTypeError('Invalid maxwait')
    if args.minblockdiff < 0 or args.minblockdiff > 600:
        raise argparse.ArgumentTypeError('Invalid minblockdiff')
    if args.inputlimit < 1 or args.inputlimit > 600:
        raise argparse.ArgumentTypeError('Invalid inputlimit')

    print('network', 'mainnet' if args.network == '' else args.network)

    delay_event = threading.Event()

    ignore_set = set()
    last_height = 0
    while True:
        data = json.loads(callrpc('listunspent', args.network, args.wallet))

        try:
            height = int(callrpc('getblockcount', args.network, args.wallet))
            if height - last_height < args.minblockdiff:
                print('Blocks since last payout less than minblockdiff setting:', height - last_height)
                raise SkipIteration
            cmd = get_sendcmd(data, ignore_set, args)
            print('\nChain Height', height)
            print('Command', cmd)
            last_height = height
            if not args.testonly:
                callrpc(cmd, args.network, args.wallet)
        except NoneOutstanding:
            print('Nothing to do.')
        except SkipIteration:
            pass
        except Exception as e:
            print('Error', e)

        wait_for = random.randint(args.minwait, args.maxwait)
        print('Waiting for {} seconds'.format(wait_for))
        delay_event.wait(wait_for)

    print('Done.')


if __name__ == '__main__':
    main()
