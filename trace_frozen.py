#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

Verifies
 - Claimed amounts and blinding factors match amount commitments.
 - Claimed anon input keyimages match those on spending txs.
   - If anon spendkeys are provided.
 - Check claimed anon index is possible.
 - Check claimed anon indices are not reused.
   - Write to file to cache across all runs
 - Keyimages are not reused.

~/tmp/particl-0.19.2.11/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile
./particl-cli -rpcwallet=wallet.dat debugwallet "{\"trace_frozen_outputs\":true}"  > ~/trace_wallets.txt
$ python trace_frozen.py ~/.particl ~/trace_wallets.txt

"""

import os
import sys
import json
import time
from util import callrpc, make_int, format8, b58decode, COIN
from ecc_util import hashToCurve, pointToCPK, G, b2i, b2h

persistent_data_file_in = os.getenv('PERSISTENT_DATA_FILE', '~/trace_frozen_data.json')
persistent_data_file = os.path.expanduser(persistent_data_file_in)


def fromWIF(x):
    return b58decode(x)[1:-5]


def main():
    use_anon_spend_keys = False
    particl_data_dir = os.path.expanduser(sys.argv[1])
    input_file = os.path.expanduser(sys.argv[2])

    if len(sys.argv) > 3:
        use_anon_spend_keys = True if sys.argv[3].lower() == 'true' else False

    chain = 'mainnet'

    authcookiepath = os.path.join(particl_data_dir, '' if chain == 'mainnet' else chain, '.cookie')
    for i in range(10):
        if not os.path.exists(authcookiepath):
            time.sleep(0.5)
    with open(authcookiepath) as fp:
        rpc_auth = fp.read()

    rpc_port = 51735 if chain == 'mainnet' else 51935

    r = callrpc(rpc_port, rpc_auth, 'getnetworkinfo')
    print('Core version', r['version'])
    print('Use anon spend keys', use_anon_spend_keys)
    print('Persistent data path', persistent_data_file_in)


    spent_anon_inputs = {}
    blacklisted_aos = []
    if os.path.exists(persistent_data_file):
        with open(persistent_data_file) as fp:
            json_data = json.load(fp)
            spent_anon_inputs = json_data['spent_anon_inputs']
            blacklisted_aos = json_data['blacklisted_aos']
    print('Spent anon indices', len(spent_anon_inputs))
    print('Blacklisted anon outputs', len(blacklisted_aos))

    with open(input_file) as fp:
        input_json = json.load(fp)

    used_keyimages = set()

    inputs_map = {}

    def trace_tx_inputs(itx, spending_txid, spending_tx, issues):
        #print(json.dumps(itx, indent=4))
        txid = itx['txid']
        tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txid, True])

        if 'ct_fee' in tx['vout'][0]:
            ct_fee = tx['vout'][0]['ct_fee']
        else:
            ct_fee = 0

        total_in = 0
        total_out = make_int(ct_fee)
        spent_out = 0  # Pass up to verify spending_txid

        claimed_outputs = []
        outputs_by_type = {}
        known_output_values = {}
        # Verify the claimed output amounts
        for txo in tx['vout']:
            txo_type = txo['type']
            if txo_type == 'data':
                continue
            outputs_by_type[txo_type] = outputs_by_type.get(txo_type, 0) + 1

            if txo_type in ['anon', 'blind']:
                found_vout = False
                for txo_verify in itx['outputs']:
                    if txo['n'] != txo_verify['n']:
                        continue

                    if spending_txid is None:
                        if txo_verify['value'] > 200 * COIN:
                            claimed_outputs.append((txo['n'], txo_type, txo_verify['anon_index'] if txo_type == 'anon' else None, txo_verify['value']))

                    try:
                        rv = callrpc(rpc_port, rpc_auth, 'verifycommitment', [txo['valueCommitment'], txo_verify['blind'], format8(txo_verify['value'])])
                        assert(rv['result'] is True)
                        total_out += txo_verify['value']
                        known_output_values[txo['n']] = (txo_type, txo_verify['value'])
                    except Exception as e:
                        warning = 'Warning: verifycommitment failed for output {} for tx {}.'.format(txo['n'], txid)
                        print(warning)
                        issues.append(warning)
                    found_vout = True

                    if txo_type == 'anon':
                        anon_index = txo_verify['anon_index']
                        if anon_index in blacklisted_aos:
                            warning = 'Warning: Blacklisted anon output: {}.'.format(anon_index)
                            print(warning)
                            issues.append(warning)

                        pubkey = txo['pubkey']
                        ao_check = callrpc(rpc_port, rpc_auth, 'anonoutput', [pubkey])
                        assert(ao_check['index'] == anon_index)

                    if spending_txid is not None and 'spent_by' in txo_verify and spending_txid == txo_verify['spent_by']:
                        spent_out += txo_verify['value']
                        # Verify anon_index is possible
                        if txo_type == 'anon':
                            anon_index = txo_verify['anon_index']
                            found_input = False
                            for txin in spending_tx['vin']:
                                for i in range(1000):
                                    row = 'ring_row_{}'.format(i)
                                    if row not in txin:
                                        break
                                    ais = txin[row].split(',')
                                    for ai in ais:
                                        if anon_index == int(ai.strip()):
                                            found_input = True
                                            break
                            assert(found_input)

                            if str(anon_index) in spent_anon_inputs:
                                assert(spent_anon_inputs[str(anon_index)] == spending_txid)
                            else:
                                spent_anon_inputs[str(anon_index)] = spending_txid

                        if txo_type == 'anon' and use_anon_spend_keys:
                            anon_sk = b2i(fromWIF(txo_verify['anon_spend_key']))
                            anon_pk = G * anon_sk
                            H = hashToCurve(pointToCPK(anon_pk))

                            expect_keyimage = H * anon_sk
                            expect_keyimage_b = pointToCPK(expect_keyimage)
                            expect_keyimage_str = b2h(expect_keyimage_b)
                            # Match keyimage to tx vin
                            found_ki = False
                            for txin in spending_tx['vin']:
                                for sd in txin['scriptdata']:
                                    if expect_keyimage_str in sd:
                                        found_ki = True
                                        break
                            assert(found_ki)

                            assert(expect_keyimage_b not in used_keyimages)
                            used_keyimages.add(expect_keyimage_b)
                    break
                if found_vout is False:
                    warning = 'Warning: Missing output {} for tx {}.'.format(txo['n'], txid)
                    print(warning)
                    issues.append(warning)
            elif txo_type == 'standard':
                total_out += txo['valueSat']
                known_output_values[txo['n']] = (txo_type, txo['valueSat'])
            else:
                warning = 'Warning: Unknown output type {} for tx {}.'.format(txo_type, txid)
                print(warning)
                issues.append(warning)

        if itx['input_type'] != 'plain' and 'inputs' in itx:
            tx_inputs = None
            if itx['inputs'] == 'repeat':
                if txid in inputs_map:
                    #tx_inputs = inputs_map[txid]
                    total_in += inputs_map[txid]
                    tx_inputs = []
            else:
                tx_inputs = itx['inputs']

            if tx_inputs is None:
                warning = 'Warning: Missing inputs for tx {}.'.format(txid)
                print(warning)
                issues.append(warning)
            else:
                for txi_verify in tx_inputs:
                    total_in += trace_tx_inputs(txi_verify, txid, tx, issues)

                if txid not in inputs_map:
                    #inputs_map[txid] = tx_inputs
                    inputs_map[txid] = total_in
        else:
            for txin in tx['vin']:
                if 'type' in txin and txin['type'] != 'standard':
                    warning = 'Warning: Missing blinded inputs for tx {}.'.format(txid)
                    print(warning)
                    issues.append(warning)
                else:
                    prev_tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txin['txid'], True])
                    prevout = prev_tx['vout'][txin['vout']]
                    if prevout['type'] != 'standard':
                        warning = 'Warning: Missing blinded inputs for tx {}.'.format(txid)
                        print(warning)
                        issues.append(warning)
                    else:
                        total_in += prevout['valueSat']

        print('txid', txid)
        if spending_txid is not None:
            print('\tinput for ', spending_txid)
        print('\ttotal_in', total_in)
        print('\ttotal_out', total_out)


        num_outputs = sum(outputs_by_type.values())
        num_known_outputs = len(known_output_values)

        print('\tOutputs known: {}/{}'.format(num_known_outputs, num_outputs))
        if num_outputs != num_known_outputs:
            for k, v in known_output_values.items():
                print('\t\t', k, *v)

            #for k, v in outputs_by_type.items():
            #    print('\t\tKnown {}: {}/{}'.format(k, outputs_by_type[k], v))

        #print('\toutputs_by_type', outputs_by_type)

        #print('total_out', total_out)
        #print('total_out', total_out)

        if total_out > total_in:
            warning = 'Warning: Mismatched value for tx: out > in {}.'.format(txid)
            print(warning)
            issues.append(warning)
        elif total_in != total_out:
            warning = 'Warning: Mismatched value for tx: in != out {}.'.format(txid)
            print(warning)
            issues.append(warning)

        if spending_txid is not None:
            return spent_out
        else:
            return claimed_outputs

    txns_likely_valid = []
    txns_check_further = []
    for itx in input_json['transactions']:
        print('')
        issues = []
        outputs = trace_tx_inputs(itx, None, None, issues)
        if len(issues) == 0:
            txns_likely_valid.append((itx['txid'], outputs))
        else:
            txns_check_further.append((itx['txid'], outputs))
    print('')

    print('Likely valid txids:')
    for pair in txns_likely_valid:
        print(pair[0])
        for output in pair[1]:
            print('    ', *output)

    print('Unproven txids:')
    for pair in txns_check_further:
        print(pair[0])
        for output in pair[1]:
            print('    ', *output)

    with open(persistent_data_file, 'w') as fp:
        json_data = {'spent_anon_inputs': spent_anon_inputs,
                     'blacklisted_aos': blacklisted_aos}
        json.dump(json_data, fp, indent=4)

    print('Done.')


if __name__ == '__main__':
    main()
