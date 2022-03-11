#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""
Move outputs to coldstake scripts.


This script creates transactions to a stake-script consisting of
the provided "stakeaddress" and a newly generated spend address.

Inputs are added from the list of unspent p2pkh outputs until either the
total value is greater than or equal to "maxvalue" or the number of
inputs equals "maxinputs".
Inputs will be grouped by address.  If "nomix" is true only inputs from
the same address will be selected.

Once a transaction has been created the script will wait for a random
interval between "minwait" and "maxwait" seconds and repeat until no
unspent p2pkh outputs are found.

The wallet must remain unlocked while the script is running.


Quit with ctrl + c

Examples:
Start Particl Desktop

Test first:
./zap.py --rpcwallet=wallet.dat --minwait=1 --maxwait=5 --testonly=1

Send to a specific stakeaddress:
./zap.py --rpcwallet=wallet.dat --nomix=true pcs19453kf98kz47yktqv7x36j39xa07mtvqx8evse
"""

__version__ = '0.1'

import os
import sys
import json
import random
import signal
import urllib
import decimal
import logging
import argparse
import threading
from xmlrpc.client import (
    Transport,
    Fault,
)

COIN = 100000000
delay_event = threading.Event()
logging.basicConfig(stream=sys.stdout, level=logging.INFO, format='%(message)s')


def jsonDecimal(obj):
    if isinstance(obj, decimal.Decimal):
        return str(obj)
    raise TypeError


class Jsonrpc():
    def __init__(self, uri, transport=None, encoding=None, verbose=False,
                 allow_none=False, use_datetime=False, use_builtin_types=False,
                 *, context=None):
        self.request_id = 0
        parsed = urllib.parse.urlparse(uri)
        if parsed.scheme not in ('http', 'https'):
            raise OSError('unsupported XML-RPC protocol')
        self.__host = parsed.netloc
        self.__handler = parsed.path
        if not self.__handler:
            self.__handler = '/RPC2'

        if transport is None:
            handler = Transport
            extra_kwargs = {}
            transport = handler(use_datetime=use_datetime,
                                use_builtin_types=use_builtin_types,
                                **extra_kwargs)
        self.__transport = transport

        self.__encoding = encoding or 'utf-8'
        self.__verbose = verbose
        self.__allow_none = allow_none

    def close(self):
        if self.__transport is not None:
            self.__transport.close()

    def json_request(self, method, params):
        try:
            connection = self.__transport.make_connection(self.__host)
            headers = self.__transport._extra_headers[:]

            self.request_id += 1
            request_body = {
                'method': method,
                'params': params,
                'id': self.request_id
            }

            connection.putrequest('POST', self.__handler)
            headers.append(('Content-Type', 'application/json'))
            headers.append(('User-Agent', 'jsonrpc'))
            self.__transport.send_headers(connection, headers)
            self.__transport.send_content(connection, json.dumps(request_body, default=jsonDecimal).encode('utf-8'))

            resp = connection.getresponse()
            return resp.read()

        except Fault:
            raise
        except Exception:
            # All unexpected errors leave connection in
            # a strange state, so we clear it.
            self.__transport.close()
            raise


def callrpc(rpc_port, auth, method, params=[], wallet=None):
    try:
        url = 'http://{}@127.0.0.1:{}/'.format(auth, rpc_port)
        if wallet is not None:
            url += 'wallet/' + urllib.parse.quote(wallet)
        x = Jsonrpc(url)
        v = x.json_request(method, params)
        x.close()
        r = json.loads(v.decode('utf-8'))
    except Exception as e:
        raise ValueError('RPC Server Error' + str(e))

    if 'error' in r and r['error'] is not None:
        raise ValueError('RPC error ' + str(r['error']))
    return r['result']


def make_int(value):
    return int(decimal.Decimal(value) * decimal.Decimal(COIN))


def format8(i):
    n = abs(i)
    quotient = n // COIN
    remainder = n % COIN
    rv = '%d.%08d' % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


def make_boolean(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ('true', '1'):
        return True
    if v.lower() in ('false', '0'):
        return False
    raise argparse.ArgumentTypeError('Boolean value expected.')


def signal_handler(sig, frame):
    logging.info('Signal {} detected, ending.'.format(sig))
    delay_event.set()


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


class Zapper():
    def __init__(self, settings):
        self.settings = settings
        self.rpc_conn = None
        self.used_outputs = set()  # Store used outputs for test only mode
        self.num_derived = 0
        self.wallet = None if self.settings.rpcwallet == '' else self.settings.rpcwallet

        logging.info('Network: {}'.format(self.settings.network))
        logging.info('Wallet: {}'.format('default' if not self.wallet else self.wallet))

        if self.settings.rpcport == 0:
            configpath = os.path.join(self.settings.datadir, 'particl.conf')
            if os.path.exists(configpath):
                with open(configpath) as fp:
                    for line in fp:
                        if line.startswith('#'):
                            continue
                        pair = line.strip().split('=')
                        if len(pair) == 2:
                            if pair[0] == 'rpcport':
                                self.settings.rpcport = int(pair[1])
                                logging.info('Set rpcport from config file: {}.'.format(self.settings.rpcport))
        if self.settings.rpcport == 0:
            self.settings.rpcport = 51735 if self.settings.network == 'mainnet' else 51935

    def callrpc(self, method, params=[]):
        return callrpc(self.settings.rpcport, self.rpc_auth, method, params, self.wallet)

    def waitForDaemonRPC(self, num_tries=10):
        for i in range(num_tries + 1):
            if delay_event.is_set():
                raise ValueError('Exiting.')
            if i == num_tries:
                delay_event.set()
                raise ValueError('Can\'t connect to daemon RPC, exiting.')
            try:
                self.callrpc('getblockchaininfo')
                break
            except Exception as ex:
                logging.warning('Can\'t connect to daemon RPC, trying again in %d second/s.' % (1 + i))
                delay_event.wait(1 + i)

    def start(self):
        logging.info('Starting zap script\n')

        # Wait for daemon to start
        authcookiepath = os.path.join(self.settings.datadir, '' if self.settings.network == 'mainnet' else self.settings.network, '.cookie')
        logging.info('Reading auth details from: {}'.format(authcookiepath))
        for i in range(10):
            if not os.path.exists(authcookiepath):
                delay_event.wait(0.5)
        with open(authcookiepath) as fp:
            self.rpc_auth = fp.read()

        self.waitForDaemonRPC()

        r = self.callrpc('getnetworkinfo')
        logging.info('Particl Core version {}'.format(r['version']))

        if self.settings.stakeaddress == '':
            r = self.callrpc('walletsettings', ['changeaddress'])
            try:
                self.settings.stakeaddress = r['changeaddress']['coldstakingaddress']
                logging.info('Set stakeaddress from walletsettings: {}'.format(self.settings.stakeaddress))
            except Exception:
                raise ValueError('Failed to set stakeaddress from walletsettings')

        r = self.callrpc('validateaddress', [self.settings.stakeaddress])
        assert(r['isvalid'] is True), 'Invalid stakeaddress'

        while True:
            if delay_event.is_set():
                return
            if not self.zap():
                break

            if not self.settings.loop:
                logging.info('Loop disabled.')
                break

            if self.settings.minwait == self.settings.maxwait:
                delay_for = self.settings.minwait
            else:
                delay_for = random.randrange(self.settings.minwait, self.settings.maxwait)

            logging.info('Waiting for {} seconds... Ctrl+c to quit.'.format(delay_for))
            delayed = 0
            while delayed < delay_for and not delay_event.is_set():
                delay_step = min(30, delay_for - delayed)
                delay_event.wait(delay_step)
                if delayed > 0:
                    logging.info('{}/{} seconds...'.format(delayed, delay_for))
                delayed += delay_step

    def selectInputs(self, groups, group_totals):
        total_value = 0
        selected = []
        addrs = sorted(group_totals, key=group_totals.get)
        for addr in addrs:
            txos = groups[addr]
            while True:
                if len(txos) < 1:
                    del groups[addr]
                    del group_totals[addr]
                    break
                if len(selected) >= self.settings.maxinputs or \
                   total_value >= self.settings.maxvalue:
                    return total_value, selected
                try:
                    txo = txos.pop()
                except Exception:
                    continue
                total_value += make_int(txo['amount'])
                selected.append(txo)

            if self.settings.nomix or self.settings.addressgroupings:
                return total_value, selected
        return total_value, selected

    def zap(self):
        utxos = self.callrpc('listunspent')

        address_groups = {}
        if self.settings.addressgroupings:
            ags = self.callrpc('listaddressgroupings')
            for ag in ags:
                if len(ag) < 2:
                    continue
                grouping_name = 'group_{:03d}'.format(len(address_groups))
                for a in ag:
                    # [addr, balance]
                    address_groups[a[0]] = grouping_name

        # Group by address
        group_totals = {}
        groups = {}
        for txo in utxos:
            if Prevout(txo['txid'], txo['vout']) in self.used_outputs:
                continue
            if 'coldstaking_address' in txo:
                continue
            if not txo['desc'].startswith('pkh('):
                continue
            addr = address_groups.get(txo['address'], txo['address'])
            if addr not in groups:
                groups[addr] = []

            # Sort from largest to smallest, selectInputs pops the list
            inserted = False
            for i in range(len(groups[addr])):
                if make_int(txo['amount']) >= make_int(groups[addr][i]['amount']):
                    groups[addr].insert(i, txo)
                    inserted = True
                    break
            if not inserted:
                groups[addr].append(txo)
            group_totals[addr] = group_totals.get(addr, 0) + make_int(txo['amount'])

        if len(groups) < 1:
            logging.info('No valid inputs')
            return False

        while True:
            total_value, inputs = self.selectInputs(groups, group_totals)
            if len(inputs) < 1:
                logging.info('No valid inputs')
                return False

            if total_value < self.settings.minvalue:
                logging.info('Skipping inputs below dust value')
                continue
            break

        internal_chain = ''
        account = self.callrpc('extkey', ['account'])
        for c in account['chains']:
            if 'function' in c and c['function'] == 'active_internal':
                internal_chain = c['chain']
                if self.settings.testonly:
                    if self.num_derived == 0:
                        self.num_derived = int(c['num_derives'])
                    r = self.callrpc('deriverangekeys', [self.num_derived, self.num_derived, internal_chain, False, False, False, True])
                    spend_address = r[0]
                    self.num_derived += 1
                else:
                    spend_address = internal_chain
                break

        addressinfo = self.callrpc('getaddressinfo', [spend_address])
        assert(addressinfo['ismine'] is True), 'Unowned spendaddress'

        cc_inputs = []
        for tx in inputs:
            if self.settings.testonly:
                self.used_outputs.add(Prevout(tx['txid'], tx['vout']))
            cc_inputs.append({'tx': tx['txid'], 'n': tx['vout']})

        options = {
            'inputs': cc_inputs,
            'test_mempool_accept': True,
            'submit_tx': not self.settings.testonly,
            'show_hex': True,
        }
        params = [
            'part',
            'part',
            [{'amount': format8(total_value), 'address': spend_address, 'stakeaddress': self.settings.stakeaddress, 'subfee': True}],
            '', '', 5, 1, False, options
        ]
        rv = self.callrpc('sendtypeto', params)
        if self.settings.testonly:
            action = 'Test'
            txid = self.callrpc('decoderawtransaction', [rv['hex'], ])['txid']
        else:
            action = 'Sent'
            txid = rv['txid']
        logging.info('{} tx: {}, inputs {}, value {}.'.format(action, txid, len(cc_inputs), format8(total_value)))
        if self.settings.testonly:
            logging.info('  hex: ' + rv['hex'])

        if len(groups) < 1:
            logging.info('Sent all')
            return False
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('-v', '--version', action='version',
                        version='%(prog)s {version}'.format(version=__version__))
    parser.add_argument('--network', dest='network', help='Chain to use [mainnet, testnet, regtest] (default=mainnet)', default='mainnet', required=False)
    parser.add_argument('--datadir', dest='datadir', help='Particl datadir (default=~/.particl)', default='~/.particl', required=False)
    parser.add_argument('--rpcport', dest='rpcport', help='RPC port, read from particl.conf or set to chain default if ommitted', type=int, default=0, required=False)
    parser.add_argument('--rpcwallet', dest='rpcwallet', help='Wallet to use', default='', required=False)
    parser.add_argument('--minvalue', dest='minvalue', help='Minimum value of transaction to create (default=0.1)', default='0.1', required=False)
    parser.add_argument('--maxvalue', dest='maxvalue', help='Maximum value of inputs to select (default=1000.0)', default='1000.0', required=False)
    parser.add_argument('--maxinputs', dest='maxinputs', help='Maximum number of inputs to select [1, 100] (default=20)', type=int, default=20, required=False)
    parser.add_argument('--nomix', dest='nomix', help='If true only inputs from the same address will be combined (default=false)', type=make_boolean, default=False, required=False)
    parser.add_argument('--addressgroupings', dest='addressgroupings', help='If true only inputs from the same address grouping will be combined, see the listaddressgroupings RPC command (default=false)', type=make_boolean, default=False, required=False)
    parser.add_argument('--minwait', dest='minwait', help='Minimum number of seconds to wait before repeating [1, 3600] (default=1)', type=int, default=1, required=False)
    parser.add_argument('--maxwait', dest='maxwait', help='Maximum number of seconds to wait before repeating [1, 7200] (default=600)', type=int, default=600, required=False)
    parser.add_argument('--loop', dest='loop', help='Exit after creating first transaction if false (default=false)', type=make_boolean, default=True, required=False)
    parser.add_argument('--testonly', dest='testonly', help='transactions are not submitted if true (default=false)', type=make_boolean, default=False, required=False)
    parser.add_argument('stakeaddress', help='The stake address to send to, read from coldstakingaddress if unset.', default='', nargs='?')

    args = parser.parse_args()

    if args.network not in ['mainnet', 'testnet', 'regtest']:
        raise argparse.ArgumentTypeError('Unknown network')
    args.minvalue = make_int(args.minvalue)
    if make_int(args.minvalue) < 1:
        raise argparse.ArgumentTypeError('Invalid minvalue')
    args.maxvalue = make_int(args.maxvalue)
    if args.maxvalue < 1:
        raise argparse.ArgumentTypeError('Invalid maxvalue')
    if args.maxinputs < 1 or args.maxinputs > 100:
        raise argparse.ArgumentTypeError('Invalid maxinputs')
    if args.minwait < 1 or args.minwait > 3600:
        raise argparse.ArgumentTypeError('Invalid minwait')
    if args.maxwait < args.minwait or args.maxwait > 7200:
        raise argparse.ArgumentTypeError('Invalid maxwait')
    if args.addressgroupings and args.nomix:
        raise argparse.ArgumentTypeError('Incompatible combination: --nomix, --addressgroupings')

    args.datadir = os.path.expanduser(args.datadir)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    rpc_app = Zapper(args)
    rpc_app.start()

    print('Done.')


if __name__ == '__main__':
    main()
