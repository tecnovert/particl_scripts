#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-0.19.2.11/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile
./particl-cli -rpcwallet=wallet.dat filtertransactions "{\"type\":\"anon\",\"count\":0,\"show_blinding_factors\":true,\"show_anon_spends\":true,\"show_change\":true}"  > ~/anons_wallet1.txt
./particl-cli -rpcwallet=wallet2.dat filtertransactions "{\"type\":\"anon\",\"count\":0,\"show_blinding_factors\":true,\"show_anon_spends\":true,\"show_change\":true}"  > ~/anons_wallet2.txt
$ python find_external_sends.py ~/anons_wallet1.txt ~/anons_wallet2.txt

"""

import os
import sys
import json


def main():

    json_inputs = []
    for i in range(1, len(sys.argv)):
        with open(os.path.expanduser(sys.argv[i])) as fp:
            json_inputs.append(json.load(fp))

    # Find all received txns
    received_outputs = {}
    for i, json_input in enumerate(json_inputs):
        for tx in json_input:
            if tx['category'] == 'receive':
                for output in tx['outputs']:
                    received_outputs[tx['txid']] = (i, tx)

    # Test all sent txns
    num_sent = 0
    for i, json_input in enumerate(json_inputs):
        for tx in json_input:
            if tx['category'] == 'send':
                num_sent += 1
                partial_receive = False
                if tx['txid'] in received_outputs:
                    #print('sent from', i)

                    recv_offset, recv_tx = received_outputs[tx['txid']]
                    #print('sent to', recv_offset)
                    #print('sent tx', json.dumps(tx, indent=4))
                    #print('recv tx', json.dumps(recv_tx, indent=4))

                    if tx['amount'] + recv_tx['amount'] == 0:
                        continue
                    partial_receive = True

                print(tx['txid'], tx['amount'])
                #print('sent tx', json.dumps(tx, indent=4))

    print('num_received', len(received_outputs))
    print('num_sent', num_sent)


if __name__ == '__main__':
    main()
