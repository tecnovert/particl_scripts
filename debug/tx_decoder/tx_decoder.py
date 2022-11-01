#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2022 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

"""

./tx_decoder.py txhex

"""

import os
import sys
import struct
from contrib.test_framework.messages import (
    PARTICL_TX_VERSION,
    OUTPUT_TYPE_STANDARD,
    OUTPUT_TYPE_DATA,
    OUTPUT_TYPE_CT,
    deser_compact_size,
    deser_vector,
    deser_string,
    CTransaction,
    FromHex,
    ToHex,
    CTxIn,
    COutPoint,
    CTxOutPart,
    CTxInWitness,
)


class CTxInDebug(CTxIn):

    def deserialize(self, f):
        print('CTxIn')
        self.prevout = COutPoint()
        self.prevout.deserialize(f)
        print('prevout', self.prevout)
        self.scriptSig = deser_string(f)
        print('scriptSig', self.scriptSig.hex())
        self.nSequence = struct.unpack("<I", f.read(4))[0]
        print('nSequence', self.nSequence)


class CTxOutPartDebug(CTxOutPart):

    def deserialize(self, f):
        if self.nVersion == OUTPUT_TYPE_STANDARD:
            self.nValue = struct.unpack("<q", f.read(8))[0]
            print('nValue', self.nValue)
            self.scriptPubKey = deser_string(f)
            print('scriptPubKey', self.scriptPubKey.hex())
        elif self.nVersion == OUTPUT_TYPE_DATA:
            self.data = deser_string(f)
        elif self.nVersion == OUTPUT_TYPE_CT:
            self.commitment = f.read(33)
            self.data = deser_string(f)
            self.scriptPubKey = deser_string(f)
            self.rangeproof = deser_string(f)
        else:
            raise ValueError(f'Unknown output type {self.nVersion}')


class CTransactionDebug(CTransaction):

    def deserialize(self, f):
        self.nVersion = int(struct.unpack("<B", f.read(1))[0])
        print('nVersion', self.nVersion)
        assert (self.nVersion == PARTICL_TX_VERSION)
        tx_type = int(struct.unpack("<B", f.read(1))[0])
        print('tx_type', tx_type)
        self.nVersion |= tx_type << 8  # tx_type is packed as the high byte of nVersion

        self.nLockTime = struct.unpack("<I", f.read(4))[0]
        print('nLockTime', self.nLockTime)

        self.vin = deser_vector(f, CTxInDebug)

        num_outputs = deser_compact_size(f)
        print('num_outputs', num_outputs)
        self.vout.clear()
        for i in range(num_outputs):
            txo = CTxOutPartDebug()
            txo.nVersion = int(struct.unpack("<B", f.read(1))[0])
            print('txo.nVersion', txo.nVersion)
            txo.deserialize(f)
            self.vout.append(txo)

        self.wit.vtxinwit = [CTxInWitness() for i in range(len(self.vin))]
        self.wit.deserialize(f)

        self.sha256 = None
        self.hash = None


def main():
    input_hex = os.path.expanduser(sys.argv[1])

    test_obj = FromHex(CTransactionDebug(), input_hex)

    test_encode = ToHex(test_obj)
    assert (input_hex == test_encode)

    print('Done.')


if __name__ == '__main__':
    main()
