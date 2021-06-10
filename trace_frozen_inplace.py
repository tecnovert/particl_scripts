#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

Verifies
 - Claimed amounts and blinding factors match amount commitments.
 - Claimed anon index matches with the chain.
 - Claimed anon input keyimages match those on spending txs.
   - If anon spendkeys are provided.
 - Check claimed anon index is possible.
 - Check claimed anon indices are not reused.
   - Write to file to cache across all runs.
 - Keyimages are not reused.
 - Unknown input amounts are feasible when compared against accumulated chain info.

~/tmp/particl-0.19.2.11/bin/particl-qt -txindex=1 -server -printtoconsole=0 -nodebuglogfile
./particl-cli -rpcwallet=wallet.dat debugwallet "{\"trace_frozen_outputs\":true}"  > ~/trace_wallets.txt
$ python trace_frozen_inplace.py ~/.particl ~/trace_wallets.txt

"""

import os
import sys
import json
import time
import sqlite3
from util import callrpc, make_int, format8, b58decode, COIN
from ecc_util import hashToCurve, pointToCPK, G, b2i, b2h

persistent_data_file_in = os.getenv('PERSISTENT_DATA_FILE', '~/trace_frozen_data.json')
persistent_data_file = os.path.expanduser(persistent_data_file_in)

chain_info_db_file_in = os.getenv('CHAIN_INFO_DB_FILE', '~/v23_anon_stats/chain_stats.db')
chain_info_db_file = os.path.expanduser(chain_info_db_file_in)


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
    print('Time', time.strftime('%Y-%m-%d %H:%M:%S %Z', time.gmtime()))
    print('Core version', r['version'])
    print('Use anon spend keys', use_anon_spend_keys)
    print('Persistent data path', persistent_data_file_in)
    print('Chain info DB path', chain_info_db_file_in)

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

    try:
        dbc = sqlite3.connect(chain_info_db_file)
    except Exception as e:
        print('chain_info_db_file not found', e)
        dbc = None

    used_keyimages = set()
    inputs_map = {}
    wallet_names = []

    def replace_wallet_name(wallet_name):
        replaced = []
        for wm in wallet_name.split(', '):
            try:
                replaced.append('wallet_{}'.format(wallet_names.index(wm)))
            except:
                wallet_names.append(wm)
                replaced.append('wallet_{}'.format(wallet_names.index(wm)))
        return ', '.join(replaced)

    def trace_tx_inputs(itx, spending_txid, spending_path, spending_tx, issues):
        #print(json.dumps(itx, indent=4))
        txid = itx['txid']
        tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txid, True])

        w_name = replace_wallet_name(itx['wallet'])
        itx['wallet'] = w_name

        if 'ct_fee' in tx['vout'][0]:
            ct_fee = tx['vout'][0]['ct_fee']
        else:
            ct_fee = 0

        itx['fee'] = ct_fee

        total_in = 0
        total_out = make_int(ct_fee)
        spent_out_values = []  # Pass up to verify spending_txid

        repeated_inputs = False

        tx_issues = []
        claimed_outputs = []
        outputs_by_type = {}
        known_output_values = {}
        known_input_values = []
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
                        tx_issues.append(warning)
                    found_vout = True

                    if txo_type == 'anon':
                        anon_index = txo_verify['anon_index']
                        if anon_index in blacklisted_aos:
                            warning = 'Warning: Blacklisted anon output: {}.'.format(anon_index)
                            tx_issues.append(warning)

                        pubkey = txo['pubkey']
                        ao_check = callrpc(rpc_port, rpc_auth, 'anonoutput', [pubkey])
                        assert(ao_check['index'] == anon_index)

                    if spending_txid is not None and 'spent_by' in txo_verify and spending_txid == txo_verify['spent_by']:
                        spent_out_values.append(txo_verify['value'])
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
                    tx_issues.append(warning)
            elif txo_type == 'standard':
                total_out += txo['valueSat']
                known_output_values[txo['n']] = (txo_type, txo['valueSat'])
            else:
                warning = 'Warning: Unknown output type {} for tx {}.'.format(txo_type, txid)
                tx_issues.append(warning)

        if itx['input_type'] != 'plain' and 'inputs' in itx:
            tx_inputs = None
            if itx['inputs'] == 'repeat':
                if txid in inputs_map:
                    #tx_inputs = inputs_map[txid]
                    total_in += inputs_map[txid]
                    tx_inputs = []
                    repeated_inputs = True
            else:
                tx_inputs = itx['inputs']

            if tx_inputs is None:
                warning = 'Warning: Missing inputs for tx {}.'.format(txid)
                tx_issues.append(warning)
            else:
                for txi_verify in tx_inputs:
                    new_spending_path = txid + ('' if spending_path == '' else ' -> ') + spending_path
                    input_values = trace_tx_inputs(txi_verify, txid, new_spending_path, tx, issues)
                    total_in += sum(input_values)
                    known_input_values += input_values

                if txid not in inputs_map:
                    #inputs_map[txid] = tx_inputs
                    inputs_map[txid] = total_in
        else:
            for txin in tx['vin']:
                if 'type' in txin and txin['type'] != 'standard':
                    warning = 'Warning: Missing blinded inputs for tx {}.'.format(txid)
                    tx_issues.append(warning)
                else:
                    prev_tx = callrpc(rpc_port, rpc_auth, 'getrawtransaction', [txin['txid'], True])
                    prevout = prev_tx['vout'][txin['vout']]
                    if prevout['type'] != 'standard':
                        warning = 'Error: Missing plain inputs for tx {}.'.format(txid)
                        tx_issues.append(warning)
                        assert(False)
                    else:
                        total_in += prevout['valueSat']
                        known_input_values.append(prevout['valueSat'])

        print('txid', txid)
        print('\ttime', time.strftime('%Y-%m-%d %H:%M:%S %Z', time.gmtime(tx['time'])))
        if spending_txid is not None:
            #print('\tinput for', spending_txid)
            print('\tinput for', spending_path)

        print('\ttotal_in', total_in)
        print('\ttotal_out', total_out)

        itx['total_in'] = total_in
        itx['total_out'] = total_out

        num_outputs = sum(outputs_by_type.values())
        num_known_outputs = len(known_output_values)

        if repeated_inputs is False:
            num_inputs = 0
            for txin in tx['vin']:
                if 'type' in txin and txin['type'] == 'anon':
                    num_inputs += txin['num_inputs']
                else:
                    num_inputs += 1

            if dbc is not None and len(known_input_values) < num_inputs:
                cur = dbc.cursor()
                total_possible_input = 0
                values_matrix = []
                for txin in tx['vin']:
                    if 'type' in txin and txin['type'] == 'blind':
                        cur.execute('SELECT value, is_estimate FROM outputs WHERE txid=? AND n=?', (txin['txid'], txin['vout']))
                        total_possible_input += cur.fetchone()[0]
                    elif 'type' in txin and txin['type'] == 'anon':
                        print('\t' + 'MLSAG rows, cols:', txin['num_inputs'], txin['ring_size'])
                        str_hdr = ''
                        for i in range(txin['ring_size']):
                            str_hdr += str(i).ljust(32)
                        print('\t' + str_hdr)

                        sum_column_vals = [0] * int(txin['ring_size'])
                        for i in range(txin['num_inputs']):
                            ring_row = txin['ring_row_{}'.format(i)]
                            ais = [int(i) for i in ring_row.split(', ')]
                            cur.execute('SELECT value, is_estimate, anon_index, spent_txid FROM outputs WHERE anon_index IN ({})'.format(','.join(['?'] * len(ais))), (ais))
                            aos = {}
                            for r in cur.fetchall():
                                ao_value, ao_is_estimate, aoi, ao_spent_txid = r
                                ao_note = ''
                                if ao_spent_txid is not None and ao_spent_txid != txid:
                                    ao_note = 'S'  # Spent elsewhere
                                if ao_is_estimate:
                                    ao_note += 'E'
                                aos[aoi] = (ao_value, ao_note)
                            str_row = ''
                            for c, ai in enumerate(ais):
                                str_row += (str(aos[ai][0]) + aos[ai][1] + ' ' + str(ai)).ljust(32)
                                sum_column_vals[c] += aos[ai][0]
                            print('\t' + str_row)
                        total_possible_input += max(sum_column_vals)
                    else:
                        num_inputs += 1
                    cur.close()

                print('\ttotal_possible_input', total_possible_input)
                itx['total_possible_input'] = total_possible_input
                if total_possible_input < total_out:
                    warning = 'Warning: possible input value < output value {}.'.format(txid)
                    tx_issues.append(warning)

            print('\tInputs known: {}/{}'.format(len(known_input_values), num_inputs))
            itx['inputs_known'] = '{}/{}'.format(len(known_input_values), num_inputs)
        else:
            itx['inputs_known'] = 'repeated'

        itx['outputs_known'] = '{}/{}'.format(num_known_outputs, num_outputs)

        print('\tOutputs known: {}/{}'.format(num_known_outputs, num_outputs))
        if num_outputs != num_known_outputs:
            for k, v in known_output_values.items():
                print('\t\t', k, *v)

        if total_out > total_in:
            warning = 'Warning: Mismatched value for tx: out > in {}.'.format(txid)
            tx_issues.append(warning)
        elif total_in != total_out:
            warning = 'Warning: Mismatched value for tx: in != out {}.'.format(txid)
            tx_issues.append(warning)

        for issue in tx_issues:
            print('\t' + issue)

        itx['issues'] = tx_issues
        issues += tx_issues

        if spending_txid is not None:
            return spent_out_values
        else:
            return claimed_outputs

    txns_likely_valid = []
    txns_check_further = []
    for itx in input_json['transactions']:
        print('')
        issues = []
        outputs = trace_tx_inputs(itx, None, '', None, issues)
        if len(issues) == 0:
            txns_likely_valid.append((itx['txid'], outputs))
        else:
            txns_check_further.append((itx['txid'], outputs))
    print('')

    print(json.dumps(input_json, indent=4))

    print('Involved wallets:', len(wallet_names))
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

    if dbc:
        dbc.close()
    print('Done.')


if __name__ == '__main__':
    main()
