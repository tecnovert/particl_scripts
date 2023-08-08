#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021-2023 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

~/tmp/particl-23.1.5.0/bin/particl-qt -server -printtoconsole=0 -nodebuglogfile
python rich_list.py ~/.particl > /tmp/rich_list.txt

"""

import os
import sys
import json
import time
import struct
import hashlib
import urllib
import decimal
import traceback
from enum import IntEnum
from xmlrpc.client import (
    Transport,
    Fault,
)
from segwit_addr import encode_segwit_address

COIN = 100000000

P2PKH_prefix = 0x38
P2SH_prefix = 0x3c
P2PKH256_prefix = 0x39
P2SH256_prefix = 0x3d


class OpCodes(IntEnum):
    OP_0 = 0x00,
    OP_PUSHDATA1 = 0x4c,
    OP_1 = 0x51,
    OP_16 = 0x60,
    OP_IF = 0x63,
    OP_ELSE = 0x67,
    OP_ENDIF = 0x68,
    OP_DROP = 0x75,
    OP_DUP = 0x76,
    OP_SIZE = 0x82,
    OP_EQUAL = 0x87,
    OP_EQUALVERIFY = 0x88,
    OP_SHA256 = 0xa8,
    OP_HASH160 = 0xa9,
    OP_CHECKSIG = 0xac,
    OP_CHECKLOCKTIMEVERIFY = 0xb1,
    OP_CHECKSEQUENCEVERIFY = 0xb2,
    OP_ISCOINSTAKE = 0xb8,


def format8(i):
    n = abs(i)
    quotient = n // COIN
    remainder = n % COIN
    rv = '%d.%08d' % (quotient, remainder)
    if i < 0:
        rv = '-' + rv
    return rv


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
        url = 'http://%s@127.0.0.1:%d/' % (auth, rpc_port)
        if wallet is not None:
            url += 'wallet/' + urllib.parse.quote(wallet)
        x = Jsonrpc(url)
        v = x.json_request(method, params)
        x.close()
        r = json.loads(v.decode('utf-8'))
    except Exception as e:
        traceback.print_exc()
        raise ValueError('RPC Server Error')

    if 'error' in r and r['error'] is not None:
        raise ValueError('RPC error ' + str(r['error']))
    return r['result']


__b58chars = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'


def b58encode(v):
    long_value = 0
    for (i, c) in enumerate(v[::-1]):
        long_value += (256**i) * c

    result = ''
    while long_value >= 58:
        div, mod = divmod(long_value, 58)
        result = __b58chars[mod] + result
        long_value = div
    result = __b58chars[long_value] + result

    # leading 0-bytes in the input become leading-1s
    nPad = 0
    for c in v:
        if c == 0:
            nPad += 1
        else:
            break
    return (__b58chars[0] * nPad) + result


def decode_var_int(fp):
    i = 0
    nB = 0
    while True:
        c = int.from_bytes(fp.read(1), 'little')
        nB += 1
        i = (i << 7) | (c & 0x7F)
        if c & 0x80:
            i += 1
        else:
            break
    return i, nB


def DecompressAmount(x):
    # x = 0  OR  x = 1+10*(9*n + d - 1) + e  OR  x = 1+10*(n - 1) + 9
    if x == 0:
        return 0
    x -= 1
    # x = 10*(9*n + d - 1) + e
    e = x % 10
    x //= 10
    n = 0
    if e < 9:
        # x = 9*n + d - 1
        d = (x % 9) + 1
        x //= 9
        # x = n
        n = x * 10 + d
    else:
        n = x + 1
    while (e):
        n *= 10
        e -= 1
    return n


def GetSpecialScriptSize(nSize):
    if nSize == 0 or nSize == 1:
        return 20
    if nSize == 2 or nSize == 3 or nSize == 4 or nSize == 5:
        return 32
    return 0


def DecompressScript(nSize, data):
    if nSize == 0x00:
        return bytes((OpCodes.OP_DUP, OpCodes.OP_HASH160, 20)) + data + bytes((OpCodes.OP_EQUALVERIFY, OpCodes.OP_CHECKSIG))
    elif nSize == 0x01:
        return bytes((OpCodes.OP_HASH160, 20)) + data + bytes((OpCodes.OP_EQUAL,))
    elif nSize == 0x02 or 0x03:
        return bytes((33, nSize)) + data + bytes((OpCodes.OP_CHECKSIG,))
    elif nSize == 0x04 or 0x05:
        print('Full size pubkey')
        exit(1)
        return bytes()
    return bytes()


def encodeAddress(address):
    checksum = hashlib.sha256(hashlib.sha256(address).digest()).digest()
    return b58encode(address + checksum[0:4])


def DecodeOP_N(opcode):
    if opcode == OpCodes.OP_0:
        return 0;
    assert  (opcode >= OpCodes.OP_1 and opcode <= OpCodes.OP_16);
    return opcode - (OpCodes.OP_1 - 1);


def ExtractAddress(script):
    script_len = len(script)

    if script_len == 25 and \
        script[0] == OpCodes.OP_DUP and \
        script[1] == OpCodes.OP_HASH160 and \
        script[2] == 20 and \
        script[23] == OpCodes.OP_EQUALVERIFY and \
        script[24] == OpCodes.OP_CHECKSIG:
        return encodeAddress(bytes((P2PKH_prefix,)) + script[3: 23])

    if script_len == 23 and \
        script[0] == OpCodes.OP_HASH160 and \
        script[1] == 20 and \
        script[22] == OpCodes.OP_EQUAL:
        return encodeAddress(bytes((P2SH_prefix,)) + script[2: 22])

    # IsPayToPublicKeyHash256
    if script_len == 37 and \
        script[0] == OpCodes.OP_DUP and \
        script[1] ==  OpCodes.OP_SHA256 and \
        script[2] ==  0x20 and \
        script[35] ==  OpCodes.OP_EQUALVERIFY and \
        script[36] ==  OpCodes.OP_CHECKSIG:
        return encodeAddress(bytes((P2PKH256_prefix,)) + script[3: 35])

    # IsPayToScriptHash256
    if script_len == 35 and \
        script[0] == OpCodes.OP_SHA256 and \
        script[1] ==  0x20 and \
        script[34] ==  OpCodes.OP_EQUAL:
        return encodeAddress(bytes((P2SH256_prefix,)) + script[2: 34])

    # IsPayToPublicKeyHash256_CS
    if script_len == 25 + 37 + 4 and \
        script[0] == OpCodes.OP_ISCOINSTAKE and \
        script[1] == OpCodes.OP_IF and \
        script[0 + 2] == OpCodes.OP_DUP and \
        script[1 + 2] == OpCodes.OP_HASH160 and \
        script[2 + 2] == 20 and \
        script[23 + 2] == OpCodes.OP_EQUALVERIFY and \
        script[24 + 2] == OpCodes.OP_CHECKSIG and \
        script[27] == OpCodes.OP_ELSE and \
        script[0 + 28] == OpCodes.OP_DUP and \
        script[1 + 28] == OpCodes.OP_SHA256 and \
        script[2 + 28] == 0x20 and \
        script[35 + 28] == OpCodes.OP_EQUALVERIFY and \
        script[36 + 28] == OpCodes.OP_CHECKSIG and \
        script[65] == OpCodes.OP_ENDIF:
        return '(' + encodeAddress(bytes((P2PKH_prefix,)) + script[3 + 2: 23 + 2]) + ', ' + encodeAddress(bytes((P2PKH256_prefix,)) + script[3+28: 3+28+32]) + ')'

    # IsPayToScriptHash256_CS
    if script_len == 25 + 35 + 4 and \
        script[0] == OpCodes.OP_ISCOINSTAKE and \
        script[1] == OpCodes.OP_IF and \
        script[0 + 2] == OpCodes.OP_DUP and \
        script[1 + 2] == OpCodes.OP_HASH160 and \
        script[2 + 2] == 20 and \
        script[23 + 2] == OpCodes.OP_EQUALVERIFY and \
        script[24 + 2] == OpCodes.OP_CHECKSIG and \
        script[27] == OpCodes.OP_ELSE and \
        script[0 + 28] == OpCodes.OP_SHA256 and \
        script[1 + 28] == 0x20 and \
        script[34 + 28] == OpCodes.OP_EQUAL and \
        script[63] == OpCodes.OP_ENDIF:
        return '(' + encodeAddress(bytes((P2PKH_prefix,)) + script[3 + 2: 23 + 2]) + ', ' + encodeAddress(bytes((P2SH256_prefix,)) + script[2 + 28: 2 + 28 + 32]) + ')'

    # IsPayToScriptHash_CS
    if script_len == 25 + 23 + 4 and \
        script[0] == OpCodes.OP_ISCOINSTAKE and \
        script[1] == OpCodes.OP_IF and \
        script[0 + 2] == OpCodes.OP_DUP and \
        script[1 + 2] == OpCodes.OP_HASH160 and \
        script[2 + 2] == 20 and \
        script[23 + 2] == OpCodes.OP_EQUALVERIFY and \
        script[24 + 2] == OpCodes.OP_CHECKSIG and \
        script[27] == OpCodes.OP_ELSE and \
        script[0 + 28] == OpCodes.OP_HASH160 and \
        script[1 + 28] == 20 and \
        script[22 + 28] == OpCodes.OP_EQUAL and \
        script[51] == OpCodes.OP_ENDIF:
        return '(' + encodeAddress(bytes((P2PKH_prefix,)) + script[3 + 2: 23 + 2]) + ', ' + encodeAddress(bytes((P2SH_prefix,)) + script[2 + 28: 2 + 28 + 32]) + ')'

    # IsPayToWitnessScriptHash
    if script_len == 34 and script[0] == OpCodes.OP_0 and script[0] == 0x20:
        # p2wsh
        return encode_segwit_address('pw', script[0], script[2:])

    # IsWitnessProgram
    if script_len >= 4 and script_len <= 42 and (script[0] == OpCodes.OP_0 or (script[0] >= OpCodes.OP_1 and script[0] <= OpCodes.OP_16)):
        # p2wpkh
        return encode_segwit_address('pw', DecodeOP_N(script[0]), script[2:])

    return 'unknown'


def main():
    particl_data_dir = os.path.expanduser(sys.argv[1])

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

    r = callrpc(rpc_port, rpc_auth, 'gettxoutsetinfo')
    print('gettxoutsetinfo', json.dumps(r, indent=4))

    r = callrpc(rpc_port, rpc_auth, 'dumptxoutset', ['/tmp/utxos', ])
    print('dumptxoutset', json.dumps(r, indent=4))

    map_scripts = {}

    sum_amount: int = 0
    nSpecialScripts = 6
    with open('/tmp/utxos', 'rb') as utxo_fp:
        block_hash = utxo_fp.read(32)

        coins_count = struct.unpack('<Q', utxo_fp.read(8))[0]
        print('coins_count', coins_count)

        for i in range(coins_count):
            txid = utxo_fp.read(32)[::-1]
            n = struct.unpack('<I', utxo_fp.read(4))[0]

            code, nb = decode_var_int(utxo_fp)
            nheight = code >> 1
            is_coinbase = code & 1

            ca = decode_var_int(utxo_fp)[0]
            amount = DecompressAmount(ca)

            script_size = decode_var_int(utxo_fp)[0]
            if script_size < 6:
                script = DecompressScript(script_size, utxo_fp.read(GetSpecialScriptSize(script_size)))
            else:
                script_size -= nSpecialScripts
                script = utxo_fp.read(script_size)

            output_type = int.from_bytes(utxo_fp.read(1), 'little')
            if output_type == 2:
                commitment = utxo_fp.read(33)

            sum_amount += amount
            if script in map_scripts:
                pair = map_scripts[script]
                pair[0] += amount
                pair[1].append(txid)
                map_scripts[script] = pair
            else:
                map_scripts[script] = [amount, [txid]]

    num_scripts_with_zero_amount: int = 0
    sort_amount_desc = sorted(map_scripts.items(), key=lambda x: x[1], reverse=True)
    for x in sort_amount_desc:
        txids = ''
        for txid in x[1][1]:
            txids += txid.hex() + ', '
        print(format8(x[1][0]), ExtractAddress(x[0]), x[0].hex(), txids)
        if x[1][0] == 0:
            num_scripts_with_zero_amount += 1

    print('sum_amount', format8(sum_amount))
    print('len(map_scripts)', len(map_scripts))
    print('num_scripts_with_zero_amount', num_scripts_with_zero_amount)


if __name__ == '__main__':
    main()
