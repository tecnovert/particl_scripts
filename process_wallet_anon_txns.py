#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-0.19.2.5/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile
./particl-cli -rpcwallet=wallet.dat filtertransactions "{\"type\":\"anon\",\"count\":0,\"show_blinding_factors\":true,\"show_anon_spends\":true,\"show_change\":true}"  > ~/anons_wallet1.txt
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

    with open(input_file) as fp:
        input_json = json.load(fp)

    num_anon_outputs = 0
    txid_set = set()
    anon_spends = []

    for r in input_json:
        txid = r['txid']
        txid_set.add(txid)

        tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txid, True])

        if 'anon_inputs' in r:
            for ai in r['anon_inputs']:
                prevtx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [ai['txid'], True])
                ao_pk = prevtx['vout'][ai['n']]['pubkey']
                ao = callrpc(rpc_port, rpc_auth, 'anonoutput', [ao_pk, ])
                ao_index = ao['index']
                anon_spends.append((ao_index, 'S', prevtx['height'], ai['txid']))

        for vout_wallet in r['outputs']:
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

    print('\nTransaction ids:')
    for txid in txid_set:
        print(txid)

    print('\nSpends:')
    for spent_ao in anon_spends:
        print(','.join(str(x) for x in spent_ao))


if __name__ == '__main__':
    main()
