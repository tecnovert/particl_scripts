#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright (c) 2021 tecnovert
# Distributed under the MIT software license, see the accompanying
# file LICENSE.txt or http://www.opensource.org/licenses/mit-license.php.

import os
import json
import logging
import subprocess
from util import dumpje


PARTICL_BINDIR = os.path.expanduser(os.getenv('PARTICL_BINDIR', '.'))
PARTICLD = 'particld'
PARTICL_CLI = 'particl-cli'
PARTICL_TX = 'particl-tx'

DATADIRS = '/tmp/parttest'


def startDaemon(node_id, bindir):
    node_dir = os.path.join(DATADIRS, str(node_id))
    command_cli = os.path.join(bindir, PARTICLD)

    args = [command_cli, '--version']
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()
    dversion = out[0].decode('utf-8').split('\n')[0]

    logging.info('Starting node ' + str(node_id) + '    ' + dversion + '\n'
                 + PARTICLD + ' ' + '-datadir=' + node_dir + '\n')
    args = [command_cli, '-datadir=' + node_dir]
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out = p.communicate()

    if len(out[1]) > 0:
        print('error ', out[1])
    return [out[0], out[1]]


def callcli(node_id, cmd):
    node_dir = os.path.join(DATADIRS, str(node_id))
    command_cli = os.path.join(PARTICL_BINDIR, PARTICL_CLI)
    args = command_cli + ' -datadir=' + node_dir + ' -rpcuser=test -rpcpassword=test ' + cmd
    p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    out = p.communicate()
    r = out[0]
    re = out[1]
    if re and len(re) > 0:
        raise ValueError('RPC error ' + str(re))
    try:
        return json.loads(r)
    except Exception:
        pass
    return r.decode('utf-8').strip()


def waitForHeight(node, nHeight, delay_event, nTries=60):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForHeight stopped.')
        ro = callcli(node, 'getblockchaininfo')
        if ro['blocks'] >= nHeight:
            return True
    raise ValueError('waitForHeight timed out.')


def stakeToHeight(node_id, height, delay_event):
    callcli(node_id, 'walletsettings stakelimit "%s"' % (dumpje({'height': height})))
    callcli(node_id, 'reservebalance false')
    waitForHeight(node_id, height, delay_event)


def stakeBlocks(node_id, num_blocks, delay_event):
    height = int(callcli(node_id, 'getblockcount'))
    stakeToHeight(node_id, height + num_blocks, delay_event)


def waitForMempool(node, txid, delay_event, nTries=10):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForMempool stopped.')
        try:
            ro = callcli(node, 'getmempoolentry {}'.format(txid))
        except Exception:
            continue
        return True
    raise ValueError('waitForMempool timed out.')


def getInternalChain(node_id):
    account = callcli(node_id, 'extkey account')
    for c in account['chains']:
        if 'function' in c and c['function'] == 'active_internal':
            return c
    raise ValueError('Internal chain not found.')


def waitForDaemonRpc(node_id, delay_event, nTries=10):
    for i in range(nTries):
        delay_event.wait(1)
        if delay_event.is_set():
            raise ValueError('waitForDaemonRpc stopped.')
        try:
            callcli(node_id, 'getnetworkinfo')
        except Exception:
            continue
        return True
    raise ValueError('waitForDaemonRpc timed out, node: {}'.format(node_id))
