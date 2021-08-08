#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-0.19.2.11/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile
./particl-cli -rpcwallet=wallet.dat filtertransactions "{\"type\":\"anon\",\"count\":0,\"show_blinding_factors\":true,\"show_anon_spends\":true,\"show_change\":true}"  > ~/anons_wallet1.txt
./particl-cli -rpcwallet=wallet.dat filtertransactions "{\"type\":\"blind\",\"count\":0,\"show_blinding_factors\":true,\"show_anon_spends\":true,\"show_change\":true}"  > ~/blinds_wallet1.txt
$ python process_wallet_anon_txns.py ~/.particl ~/anons_wallet1.txt > ~/anon1.txt

"""

import os
import sys
import json
import time
from util import callrpc, make_int


def main():
    particl_data_dir = os.path.expanduser(sys.argv[1])
    input_file = os.path.expanduser(sys.argv[2])

    chain = 'mainnet'

    authcookiepath = os.path.join(particl_data_dir, '' if chain == 'mainnet' else chain, '.cookie')
    for i in range(10):
        if not os.path.exists(authcookiepath):
            time.sleep(0.5)
    with open(authcookiepath) as fp:
        rpc_auth = fp.read()

    rpc_port = 51735 if chain == 'mainnet' else 51935

    r = callrpc(rpc_port, rpc_auth, 'getnetworkinfo')
    print('version', r['version'])

    json_objs = []
    with open(input_file) as fp:
        end_char = None
        json_txt = ''
        for line in fp:
            sline = line.rstrip()
            if end_char is None:
                if sline == '[':
                    end_char = ']'
                elif sline == '{':
                    end_char = '}'

            if end_char is not None:
                json_txt += line

                if sline == end_char:
                    json_objs.append(json.loads(json_txt))
                    json_txt = ''
                    end_char = None

    num_anon_outputs = 0
    txid_set = set()
    anon_spends = {}
    ct_values = []

    def inspect_traced_frozen_tx(tx):
        for output in tx['outputs']:
            n = output['n']
            output_amount = output['value']
            blindingfactor = output['blind']
            if output['type'] == 'anon':
                ao_index = output['anon_index']
                ao = callrpc(rpc_port, rpc_auth, 'anonoutput', [str(ao_index)])
                pubkey = ao['publickey']
                print('%d,%s,%d,%s' % (ao_index, pubkey, output_amount, blindingfactor))

                if 'spent_by' in output:
                    spendtx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [output['spent_by'], True])
                    anon_spends[ao_index] = (spendtx['height'], output['spent_by'])

            elif output['type'] == 'blind':
                ct_values.append((tx['txid'], n, output_amount, blindingfactor))

        if 'inputs' in tx and not isinstance(tx['inputs'], str):
            print('Anon values:')
            for txi in tx['inputs']:
                inspect_traced_frozen_tx(txi)

    for input_json in json_objs:
        if isinstance(input_json, dict):
            if 'frozen_outputs' in input_json:
                # Output from: debugwallet "{\"trace_frozen_outputs\":true}"
                print('\nSpends:')
                for tx in input_json['frozen_outputs']:
                    if 'anon_index' in tx:
                        print('{},U'.format(tx['anon_index']))
                    elif tx['type'] == 'anon':
                        tx_in_chain = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [tx['txid'], True])
                        ao_pk = tx_in_chain['vout'][tx['n']]['pubkey']
                        ao = callrpc(rpc_port, rpc_auth, 'anonoutput', [ao_pk, ])
                        print('{},U'.format(ao['index']))
            else:
                # Output from: debugwallet "{\"trace_frozen_outputs\":true}"
                for tx in input_json['transactions']:
                    inspect_traced_frozen_tx(tx)
        else:
            # Output from filtertransactions
            print('Anon values:')
            for r in input_json:
                txid = r['txid']
                txid_set.add(txid)

                try:
                    tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txid, True])
                except Exception as e:
                    # No such mempool or blockchain transaction.
                    print('Error: getrawtransaction:', txid, str(e), file=sys.stderr)
                    continue

                if 'anon_inputs' in r:
                    for ai in r['anon_inputs']:
                        prevtx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [ai['txid'], True])
                        ao_pk = prevtx['vout'][ai['n']]['pubkey']
                        ao = callrpc(rpc_port, rpc_auth, 'anonoutput', [ao_pk, ])
                        ao_index = ao['index']
                        anon_spends[ao_index] = (tx['height'], txid)

                for vout_wallet in r['outputs']:
                    if 'type' not in vout_wallet:
                        # standard tx
                        continue
                    if vout_wallet['type'] == 'anon':
                        num_anon_outputs += 1
                        output_amount = make_int(vout_wallet['amount'])

                        if output_amount < 0:
                            continue

                        if vout_wallet['vout'] == 65535:
                            print('reconstructed')  # Should only happen when output_amount > 0
                        pubkey = tx['vout'][vout_wallet['vout']]['pubkey']

                        ao = callrpc(rpc_port, rpc_auth, 'anonoutput', [pubkey, ])
                        ao_index = ao['index']

                        print('%d,%s,%d,%s' % (ao_index, pubkey, output_amount, vout_wallet.get('blindingfactor', 'NONE')))
                    elif vout_wallet['type'] == 'blind':
                        if 'blindingfactor' not in vout_wallet:
                            continue
                        output_amount = make_int(vout_wallet['amount'])
                        blindingfactor = vout_wallet['blindingfactor']
                        n = vout_wallet['vout']
                        ct_values.append((txid, n, output_amount, blindingfactor))

    print('\nTransaction ids:')
    for txid in txid_set:
        print(txid)

    print('\nSpends:')
    for aoi, spent_info in anon_spends.items():
        print('{},S,{},{}'.format(aoi, spent_info[0], spent_info[1]))

    print('\nCT values:')
    for ctv in ct_values:
        print(','.join(str(x) for x in ctv))


if __name__ == '__main__':
    main()
