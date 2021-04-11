#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib

from ecc_util import (
    ep, G,
    b2h, b2i, i2b, i2h, h2b,
    ToDER, pointToCPK2, pointToCPK, CPKToPoint,
    hashToCurve, validKey
)
from contrib.rfc6979 import secp256k1_rfc6979_hmac_sha256_initialize, secp256k1_rfc6979_hmac_sha256_generate
from contrib.ellipticcurve import INFINITY

COIN = 100000000


class RCTOutput():
    __slots__ = ('amount', 'privkey', 'pubkey', 'blind', 'commitment')

    def __init__(self, amount, privkey, blind):
        self.amount = amount
        self.privkey = privkey
        self.blind = blind


class MLSAG():
    __slots__ = ('keyimages', 'sig_c', 'sig_s')

    def __init__(self):
        self.keyimages = []
        self.sig_c = None
        self.sig_s = []

    def keyimages_bytes(self):
        rv = bytearray()
        for keyimage in self.keyimages:
            rv += keyimage
        return rv

    def sig_c_bytes(self):
        return self.sig_c

    def sig_s_bytes(self):
        rv = bytearray()
        for s in self.sig_s:
            rv += s
        return rv


def generateMLSAG(rows, cols, real_column, nonce, preimage, secret_keys, pk_matrix_with_last_row):
    print('generateMLSAG')

    sig = MLSAG()
    sig.sig_s = [None] * rows * cols
    csprng = secp256k1_rfc6979_hmac_sha256_initialize(nonce + preimage)
    h = hashlib.sha256(preimage)
    alpha = []

    for k in range(0, rows):
        ba = secp256k1_rfc6979_hmac_sha256_generate(csprng, 32)
        a = b2i(ba)
        alpha.append(a)
        A = G * a

        offset = (real_column + k * cols) * 33
        Pb = pk_matrix_with_last_row[offset: offset + 33]
        h.update(Pb)
        h.update(pointToCPK(A))

        # Skip non-ds rows
        if k >= rows - 1:
            continue

        E = hashToCurve(Pb)
        J = E * a
        h.update(pointToCPK(J))

        offset = k * 32
        KI = E * b2i(secret_keys[offset: offset + 32])
        sig.keyimages.append(pointToCPK(KI))

    hash_result = h.digest()

    last_c = b2i(hash_result)

    i = (real_column + 1) % cols
    if i == 0:
        sig.sig_c = hash_result

    while i != real_column:
        h = hashlib.sha256(preimage)

        for k in range(0, rows):
            bs = secp256k1_rfc6979_hmac_sha256_generate(csprng, 32)
            sig.sig_s[i + k * cols] = bs
            s = b2i(bs)
            offset = (i + k * cols) * 33
            Pb = pk_matrix_with_last_row[offset: offset + 33]
            L = G * s + CPKToPoint(Pb) * last_c

            h.update(Pb)
            h.update(pointToCPK(L))

            # Skip non-ds rows
            if k >= rows - 1:
                continue

            # R = H(pk[k][i]) * ss + ki[k] * clast
            R = hashToCurve(Pb) * s + CPKToPoint(sig.keyimages[k]) * last_c
            h.update(pointToCPK(R))

        hash_result = h.digest()
        last_c = b2i(hash_result)

        i = (i + 1) % cols
        if i == 0:
            sig.sig_c = hash_result

    for k in range(0, rows):
        # ss[k][index] = alpha[k] - clast * sk[k]
        sk = b2i(secret_keys[k * 32: k * 32 + 32])
        sig.sig_s[real_column + k * cols] = i2b(((alpha[k] - ((last_c * sk)) % ep.o)) % ep.o)

    return sig


def verifyMLSAG(rows, cols, preimage, pk_matrix_with_last_row, sig):
    print('verifyMLSAG')

    c_verify = sig.sig_c

    for i in range(0, cols):
        h = hashlib.sha256(preimage)

        for k in range(0, rows):
            # L = G * ss + pk[k][i] * clast
            offset = (i + k * cols) * 33
            Pb = pk_matrix_with_last_row[offset: offset + 33]
            P = CPKToPoint(Pb)
            s = b2i(sig.sig_s[i + k * cols])
            c = b2i(c_verify)
            L = G * s + P * c

            h.update(Pb)
            h.update(pointToCPK(L))

            # Skip non-ds rows
            if k >= rows - 1:
                continue

            # R = H(pk[k][i]) * ss + ki[k] * clast
            R = hashToCurve(Pb) * s + CPKToPoint(sig.keyimages[k]) * c
            h.update(pointToCPK(R))

        c_verify = h.digest()

    return True if c_verify == sig.sig_c else False


def main():
    HG = hashToCurve(ToDER(G))
    print('G: ', b2h(ToDER(G)))
    print('HG:', b2h(ToDER(HG)))

    rct_prev_outs = []

    skc = 1
    for i in range(6):
        amount = 10 * COIN

        privkey = b2i(bytes([skc] * 32))
        skc += 1
        blind = b2i(bytes([skc] * 32))
        skc += 1
        assert(validKey(privkey))
        assert(validKey(blind))
        prevout = RCTOutput(amount, privkey, blind)

        prevout.commitment = G * prevout.blind + HG * prevout.amount
        prevout.pubkey = G * prevout.privkey

        rct_prev_outs.append(prevout)

    prevouts_matrix = [rct_prev_outs[0: 3], rct_prev_outs[3:]]
    print(prevouts_matrix)

    rows = 2  # Including commitments row
    cols = 3
    real_column = 0
    print('\nrows, cols, real_column', rows, cols, real_column)

    privkey = b2i(bytes([skc] * 32))
    skc += 1
    blind = b2i(bytes([skc] * 32))
    skc += 1
    rct_output = RCTOutput(9 * COIN, privkey, blind)

    rct_output.commitment = G * rct_output.blind + HG * rct_output.amount
    assert(b2h(pointToCPK2(rct_output.commitment)) == '08e580193a3f2bca953c2ce92396f368d875a11d7867a92948fe632b17c8227788')

    output_commitments = []
    output_commitments.append(rct_output.commitment)

    fee_output_amount = 1 * COIN
    blind = 0
    fee_commitment = HG * fee_output_amount
    output_commitments.append(fee_commitment)

    commitment_matrix = []
    hex_pk_matrix = ''
    for k in range(rows - 1):
        commitment_row = []
        for i in range(cols):
            hex_pk_matrix += b2h(pointToCPK(prevouts_matrix[k][i].pubkey))
            commitment_row.append(prevouts_matrix[k][i].commitment)
        commitment_matrix.append(commitment_row)

    blinding_factors = []
    blinding_factors_in_sum = 0
    for i in range(rows - 1):
        bf = prevouts_matrix[i][real_column].blind
        blinding_factors.append(bf)
        blinding_factors_in_sum = (blinding_factors_in_sum + bf) % ep.o

    # Add output blinding factors
    blinding_factors.append(rct_output.blind)
    blinding_factors_out_sum = rct_output.blind

    hex_pk_matrix_with_last_row = hex_pk_matrix
    mlsag_commitment_row = []
    sum_output_commits = INFINITY
    for oc in output_commitments:
        sum_output_commits += oc

    for i in range(cols):
        sum_input_commits = INFINITY
        for cr in commitment_matrix:
            sum_input_commits += cr[i]

        commitment_sum = sum_input_commits - sum_output_commits
        hex_pk_matrix_with_last_row += b2h(pointToCPK(commitment_sum))
        print('commitment_sum', i, b2h(pointToCPK(commitment_sum)))

    blinding_factor_diff = (blinding_factors_in_sum - blinding_factors_out_sum) % ep.o
    print('G * blinding_factor_diff', b2h(pointToCPK(G * blinding_factor_diff)))

    nonce = bytes([skc] * 32)
    skc += 1
    preimage = bytes([skc] * 32)
    skc += 1

    print('Nonce:       ', b2h(nonce))
    print('Preimage:    ', b2h(preimage))

    secret_keys = bytearray()
    for i in range(rows - 1):
        secret_keys += i2b(prevouts_matrix[i][real_column].privkey)
    secret_keys += i2b(blinding_factor_diff)

    sig = MLSAG()
    sig.sig_s = [None] * rows * cols
    csprng = secp256k1_rfc6979_hmac_sha256_initialize(nonce + preimage)

    alpha = []

    sig = generateMLSAG(rows, cols, real_column, nonce, preimage, secret_keys, h2b(hex_pk_matrix_with_last_row))
    print('keyimages', b2h(sig.keyimages_bytes()))
    print('sig_c', b2h(sig.sig_c_bytes()))
    print('sig_s', b2h(sig.sig_s_bytes()))

    h = hashlib.sha256()
    h.update(sig.keyimages_bytes())
    h.update(sig.sig_c_bytes())
    h.update(sig.sig_s_bytes())
    assert(h.hexdigest() == '48238c7b4c9884881f7d7d4556d72df43bb5f7004a07574285a3f535b68c38f7')

    assert(verifyMLSAG(rows, cols, preimage, h2b(hex_pk_matrix_with_last_row), sig) is True)

    rows = 3  # Including commitments row
    cols = 3
    real_column = 2
    print('\nrows, cols, real_column', rows, cols, real_column)

    skc += 1  # Bump to avoid blind sum_in == sum_out
    privkey = b2i(bytes([skc] * 32))
    skc += 1
    blind = b2i(bytes([skc] * 32))
    skc += 1
    rct_output = RCTOutput(19 * COIN, privkey, blind)
    rct_output.commitment = G * rct_output.blind + HG * rct_output.amount
    print('rct_output.commitment', b2h(pointToCPK2(rct_output.commitment)))
    assert(b2h(pointToCPK2(rct_output.commitment)) == '093cd5ef96dd96e08365b42e72837af7b603ddfbc6317a7d02b258e08657299562')

    output_commitments = []
    output_commitments.append(rct_output.commitment)

    fee_output_amount = 1 * COIN
    fee_commitment = HG * fee_output_amount
    output_commitments.append(fee_commitment)

    commitment_matrix = []
    hex_pk_matrix = ''
    for k in range(rows - 1):
        commitment_row = []
        for i in range(cols):
            hex_pk_matrix += b2h(pointToCPK(prevouts_matrix[k][i].pubkey))
            commitment_row.append(prevouts_matrix[k][i].commitment)
        commitment_matrix.append(commitment_row)

    blinding_factors = []
    blinding_factors_in_sum = 0
    for i in range(rows - 1):
        bf = prevouts_matrix[i][real_column].blind
        blinding_factors.append(bf)
        blinding_factors_in_sum = (blinding_factors_in_sum + bf) % ep.o

    # Add output blinding factors
    blinding_factors.append(rct_output.blind)
    blinding_factors_out_sum = rct_output.blind

    hex_pk_matrix_with_last_row = hex_pk_matrix
    mlsag_commitment_row = []
    sum_output_commits = INFINITY
    for oc in output_commitments:
        sum_output_commits += oc

    for i in range(cols):
        sum_input_commits = INFINITY
        for cr in commitment_matrix:
            sum_input_commits += cr[i]

        commitment_sum = sum_input_commits - sum_output_commits
        hex_pk_matrix_with_last_row += b2h(pointToCPK(commitment_sum))
        print('commitment_sum', i, b2h(pointToCPK(commitment_sum)))

    blinding_factor_diff = (blinding_factors_in_sum - blinding_factors_out_sum) % ep.o
    print('blinding_factor_diff', i2h(blinding_factor_diff))
    print('G * blinding_factor_diff', b2h(pointToCPK(G * blinding_factor_diff)))

    print('Nonce:       ', b2h(nonce))
    print('Preimage:    ', b2h(preimage))

    secret_keys = bytearray()
    for i in range(rows - 1):
        secret_keys += i2b(prevouts_matrix[i][real_column].privkey)
    secret_keys += i2b(blinding_factor_diff)

    print('secret_keys', b2h(secret_keys))

    sig = MLSAG()
    sig.sig_s = [None] * rows * cols
    csprng = secp256k1_rfc6979_hmac_sha256_initialize(nonce + preimage)

    alpha = []

    sig = generateMLSAG(rows, cols, real_column, nonce, preimage, secret_keys, h2b(hex_pk_matrix_with_last_row))
    print('keyimages', b2h(sig.keyimages_bytes()))
    print('sig_c', b2h(sig.sig_c_bytes()))
    print('sig_s', b2h(sig.sig_s_bytes()))

    h = hashlib.sha256()
    h.update(sig.keyimages_bytes())
    h.update(sig.sig_c_bytes())
    h.update(sig.sig_s_bytes())
    assert(h.hexdigest() == '7c5929f503bf9e15f5e6382fd7f1780a2dc099d10e6a673aaadedf036e463eb7')

    assert(verifyMLSAG(rows, cols, preimage, h2b(hex_pk_matrix_with_last_row), sig) is True)

    print('Done')


if __name__ == '__main__':
    main()
