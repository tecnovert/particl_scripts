
Start a node in regtest mode:

    mkdir -p /tmp/test1
    ./particld --daemon --regtest --nocheckpeerheight --minstakeinterval=2 --datadir=/tmp/test1

    alias PART_CLI="./particl-cli --regtest --datadir=/tmp/test1"


Get version:

    PART_CLI getnetworkinfo | jq -r .version
    23020600


Check indices:

    PART_CLI getinsightinfo | jq -r .txindex
    false


Create two wallets, send and receive.
Import both wallets from mnemonics, the send wallet mnemonic can access outputs embedded in the regtest genesis block.
Reduce the stake combine and split thresholds as the moneysupply on the regtest network is low.

    PART_CLI createwallet send
    PART_CLI -rpcwallet=send walletsettings stakingoptions "{\"stakecombinethreshold\":100,\"stakesplitthreshold\":200}"
    PART_CLI -rpcwallet=send extkeyimportmaster "abandon baby cabbage dad eager fabric gadget habit ice kangaroo lab absorb"

    PART_CLI createwallet receive
    PART_CLI -rpcwallet=receive extkeyimportmaster "suspect flower butter inside absorb say bleak swallow try bread practice audit chunk bulb rare initial moment glance glimpse keen cinnamon shop occur meadow"

Create a stealth address for the spend wallet and send some coins into blinded (ct) and anon (rct) balances.
Create multiple anon outputs as multiple anon outputs are required as mixins (decoy inputs) to create anon spending transactions.

    export SX_ADDR_1=$(PART_CLI -rpcwallet=send getnewstealthaddress)
    PART_CLI -rpcwallet=send sendtypeto part blind "[{\"address\":\"$SX_ADDR_1\",\"amount\":100}]"
    for i in {1..8}; do PART_CLI -rpcwallet=send sendtypeto part anon "[{\"address\":\"$SX_ADDR_1\",\"amount\":20}]"; done

Wait 12 blocks for the anon balance to be stakeable

    PART_CLI -rpcwallet=send getwalletinfo
        "immature_anon_balance": 160.00000000,

    until echo $(PART_CLI -rpcwallet=send getwalletinfo | jq -r .anon_balance) | grep -m 1 "160"; do echo "height: $(PART_CLI getblockcount)" && sleep 2 ; done


Create a normal address for the receive wallet and send three transactions to it, one from each balance type.
Reduce the ring size for the anon -> part tx to 5

    export ADDR_2=$(PART_CLI -rpcwallet=receive getnewaddress)

    export TXID_PLAIN=$(PART_CLI -rpcwallet=send sendtypeto part part "[{\"address\":\"$ADDR_2\",\"amount\":10}]")
    export TXID_BLIND=$(PART_CLI -rpcwallet=send sendtypeto blind part "[{\"address\":\"$ADDR_2\",\"amount\":10}]")
    export TXID_ANON=$(PART_CLI -rpcwallet=send sendtypeto anon part "[{\"address\":\"$ADDR_2\",\"amount\":10}]" "" "" 5)


    export TXID_ANON=$(PART_CLI -rpcwallet=send sendtypeto anon part "[{\"address\":\"$ADDR_2\",\"amount\":10}]" "" "" 5)

    PART_CLI -rpcwallet=receive gettransaction $TXID_PLAIN
    {
      "amount": 10.00000000,
      "type_in": "plain",
      "confirmations": 4,
      "blockhash": "9bbc18a4c2bb3c134e8bda4708ac1def772517a7b6c1ec39399d182b4d61cd5d",
      "blockheight": 156,
      "blockindex": 3,
      "blocktime": 1694095342,
      "txid": "2ae6b6260cda8e7cae16a4f62ef43f8d9071b6982652c5f9169d28eb730907f7",
      "walletconflicts": [
      ],
      "time": 1694095341,
      "timereceived": 1694095341,
      "bip125_replaceable": "no",
      "details": [
        {
          "address": "prMj6ZiZRcdix84NdtBfP7weM9U9Zwi1RP",
          "category": "receive",
          "amount": 10.00000000,
          "label": "",
          "account": "",
          "vout": 1
        }
      ],
      "hex": "a0009b00000001fdf7d33980da74d0ba78a4898aa6e23474bda4cc6e6b9deca6c9832312b347140100000000feffffff020123a16e2c0e0000001976a9149a51836fa1827f6d2fa17cf82a1669f5847e60e088ac0100ca9a3b000000001976a914eb90825690fa983b658e9f06ec394a4e887dc1b988ac0247304402205727003e9e95cd554fe8d7777132c10f252f43de702780222044771fdf7a0a0002202e1bf21a7b7d82f47690eee59940705e3c384d6d99352b9810ef849b48cdec9101210256f1892886fac8fb0dc67c10cdb7eba57beb1161fd4376d42e5637cb3dacefd6"
    }

    PART_CLI -rpcwallet=receive gettransaction $TXID_BLIND
    {
      "confirmations": 22,
      "blockhash": "9bbc18a4c2bb3c134e8bda4708ac1def772517a7b6c1ec39399d182b4d61cd5d",
      "blockindex": 2,
      "blocktime": 1694095342,
      "txid": "2a70e0de88c8b27d3462de3b37b4fc7ae224eb8463315304050fb82bb6e173b0",
      "walletconflicts": [
      ],
      "time": 1694095341,
      "timereceived": 1694095341,
      "amount": 10.00000000,
      "type_in": "blind",
      "details": [
        {
          "account": "",
          "address": "prMj6ZiZRcdix84NdtBfP7weM9U9Zwi1RP",
          "category": "receive",
          "type": "standard",
          "amount": 10.00000000,
          "vout": 3
        }
      ],
      "hex": "a0009b00000001fc40b37eb9f0c202b5ff2a076c5b71d3a41c1be8ef3f42d25254409745d234a90100000000feffffff04040406c0b30c0208cf770d5ee5a087a98a48dcebe8f731e1f14adfca07480dad98066c1da25a55322103983423dc77717634d1a1d8c4d48a376faef0b257a977bbfb3ea72905e7843db61976a9148e64eab1fea0551c92df810b21944702fcb905c288acfda30211157cd9ae9e96e50d2d37fbac333caa03e56fdd01a9053781f5c181625077470ca062b0c5ac73f5032e0626ca9f41b443dfed9e3c76ba1b4b54b6532760648f085fe060ddab71c01d1c039b3f9acd986a780efc5e6b7ae2abfcda84e64ad8ebd4b415eabd252bd958aa08f08d392839d066a3f3b2d4f371dbcdf0f357f7741d5268542232de602f497bb371a795d1a00864b63ca024b033e9f8b5f984e710ff93e50f4dc87e8655fdd3df0209165c8866e7e7ddc92bb57563f3b5a1363163fcbebaf12e68289560bde15cc3be500b4dd4d890313776e6a824b2836b919fad881f6a084667b2c7170c0d5612855ad1f5d78b1530ce916ec644bda152dedc87cb282faff852d126e12cddceb0d8023b28f94b51d9698d501eeaa7ad6c98603a282f5677111a480a6098a5d88255ea50ea547017bd7bb38e388f0942dda7409b0d94fe993b80672d3fab02c4ed5c066fbfe8fd67768d8367129b39b3460788a38c454c022e4e979b7fd96bbfafda23d4271cc295f673fd39a3c1238ea221917cb7d731fe842922a743f8f0e41be874731b0ad2d909cfe4047539f136e9f21ac62505b7635d004450c1de4ff304880ffec905fd5cd341fb9ebaed74adf577fa4cddfafb0ad419ac4306e6c17392b638b085c1bd941d552e5c6cd7fd86b1e62f900541f69d6a442cdad43ba7dfbe53b9e4a37bccb81dd895ba89ed3c3a07418e94d64308ef00dde1e05444fb80e69f4dc53ff7af4ccb0fe169999dc7dcb733e470b278ef6eec94ff2a10f38880b8cd3d1a24fd698e81495570965a7653482c0029f82cadfda69eb49ec6be4b1d4f6f1527052eb384e1e0b8d655908209e7c267b1f04ee0b5fe86e6d250ae8c2e82744c7174991b3975e79eb0bf2bce486b936e0206904ff15715a07d3341ca2bceaa0ebc63e6fd5479a42de2dca8002bd51ab5fa3483cf9702084bd1938548649a9d566d8df0a96a7b8a6edeb6d220ba0148fd52e02254ee6bf9210208327598f9b5f0af25d6a1ecfcff55a470eefab5478d4df96bc7dcfb431c40031976a9148e64eab1fea0551c92df810b21944702fcb905c288acfda302fddb3064f3c5f0b03bb391075ea1c7ffe15568ed70ea61514ba1f9a4055ae3726df52511d9c999e6058426b350c647ecc7b37d2cc128b4a2f5cc904aeca1f7e8023142e5646f24c1740b12d5334b509ab89f929276ba9b3ceb948a0807041737dc2cad6b77f70053e2dbdac90ec74070dac0cce31dbe5ad0a2baea135b75846d41387045f49f54edf8d927dfa0231aad3d71636b26698815f9ad6180a846df022c982ed2395bd4abaec2262df5898829639fd8853d6f595e98d90b605a34718ee9ddb44f9f94503decad4a84209ca65081925a0cc12db7673926caddaf9da8a0998c79a20227a7c3d97f21bad8ddf3dc66a7de6533f920d674f5188e8cc88bd63c57137b175f4d920afba417d22b3cf501234bd736c05f79a05eeb6a73e8c6922d052f6fcc21349cc6328cdc20d4260b0ac46a716fcb67c7c0b71f58b1eb104c79628becb67bce7a15fd6c3ede14402618a6e930423a7abc0e53f8fd60a02478210500b95142373ded6145a7aa71c3cc0f6290390a3033b253a65222905349b66b3299b2d417ec94f3c14ece0f3b27b9583c19dc05ac4a10b935e94337999d01f6b4c0f816a9103c8c6afde197848758a4998697602ec5634a53d6fcbd5854fcdfb30813b02a45c24b9d3311d26d27390e5e7d1aa831b13b94f143690d8ea0009a3bf9910727c444dde81e9a80092cb634219669c48d6890e09a86fd6d6fc95df1a17b5e54d3d7842e0091c1201c784cf9b5e6ed483ab6ed6d4f98515fef6d87562ecf0d8d068c60e0d3f26f33ca43ca33d6f9523c9ff42af32a7bb16da9d908f61e9fb77701d087c15a288ef04af6ad1ca7c7c71730c2af1eaa0f7496f162b881eb8b89df97937ba0a2847dc8cdd04f2a83921c9293ebc20c502959cc89da1e0fd8d6cefa187183d41fa5dd5df4be04c4a01d47c7e26a80899175b4bff02759c3a4b70100ca9a3b000000001976a914eb90825690fa983b658e9f06ec394a4e887dc1b988ac02473044022028f0f4f92964957c96322dbd76c60e30ac0644b599f7fa35f91dc605cd8a28c702203d49518e71ae984838a4074cfb92089969e1c4e5d91b9f1d7e910ad6ac912783012103baa1fa0f4dfb94d5125c026cd2cb9813aca96bc98911c5e1acf81888896a58bd"
    }


    PART_CLI -rpcwallet=receive gettransaction $TXID_ANON
    {
      "confirmations": 28,
      "blockhash": "071e1f31b18e7776eb53da2effafc497380fa4f92e187a627ff17ca4f69376e4",
      "blockindex": 1,
      "blocktime": 1694095348,
      "txid": "ec7b5c247382e46ec9a7cbcb513ecd4e5db61b83045f7830c5ec8898496fe744",
      "walletconflicts": [
      ],
      "time": 1694095347,
      "timereceived": 1694095347,
      "amount": 10.00000000,
      "type_in": "anon",
      "details": [
        {
          "account": "",
          "address": "prMj6ZiZRcdix84NdtBfP7weM9U9Zwi1RP",
          "category": "receive",
          "type": "standard",
          "amount": 10.00000000,
          "vout": 1
        }
      ],
      "hex": "a00000000000010100000005000000000000000000000000000000000000000000000000000000a0ffffff00ffffffff0121038a5927607fdb7a56c2939cf940ccce9386d15b78f9a2ea00c0262025381656f30304040680ae120100ca9a3b000000001976a914eb90825690fa983b658e9f06ec394a4e887dc1b988ac03036e1165a3a89f98e209b184dcb259316e3ca23713c69a21b2bc8df9674282f26a092a46bfc0a548276a5654fefbebdcbb801e9973c7da79eb2d3a4d97e4bc06d14c2102c8b676bcc4722cd1ae24db5026d6ea2d4ec8b39eead30d80cbbdd7778c535b6ffda30250bd6927b574d38f7cb770122d504548e60d486e8719b4b007f1e008f600e864e24b3cacde02b3dfd9c3620cbd68f943c9324805dbe8f05ff6c767cc50c8407c04466bd9f182c65877f180d5a4a4a2f55c17b1fc321877ec5868b25a277b96fac21e671a09f6ca8722f0acd16bef73e690f7bfcbf23d2470bd17870f303171aaacbc022479a49a54669f92c1efafb9ede68e15246140338a84791a1b7d2c043a7d4000169986dd2dec4cd36299b374e3dcbf5390db8091decaaf7ca10a3182f12310c894e524fb7c88731f37e9b9f62bf7cc094f7e68149c313ac715a1daa9bdc39cba5e04c2809f022e276ee7e1bc97a1c25d844da8c5c39e972ca8ea54e0bdec5f099ade08e914d5c416a2da117dc87598d270f0fb225106f2ab9a4b80481ee420d77287665640bc1ee0bf9845d5afa7fe71e62c6f9204ecda6c57b365a0f887119266543ddf4dfadc33855c9d18e2650a3f3f5217b9a2d1bdee4203a54c16772102d6d2586d8dd5ae71a7c6c3e78876a42d049c32aaa60bee105f25341347d4710aad04a36cd5e6ba20cceb10697e7c0beaa1e96d103604cc0439d75c1d6693f513f595266c7533230b5fa23ec6825dc6d3d20b5cb6fa699757d5dc28ffc56c116fae8c9e0e3b825d74116ae4cff0640cbda72bd667303f80e1e1ab0a152d0381da06a9640fae434858ba36d0d5c7dc1f61fc3f16ee4a18f8fb680b1182de7c62575ba750733e0e0fafaa535b22ccfb580fcf9870db6226fd664d423d503f55db6ff5a9840fb0183721749356cbf6bd34c79ac3bee50c60ed957a0b9cbd463f0b8798c1ae24bf7bccc7c73cec892949c4e573a93f4ee77906220c940e922be60c8be15430516d9c3621a370d0db1ed5e7210f3a29c2ee7c9ffedbc3610b14f35c16a460e0f2aad89b1368dc1d9ddc2c6a021cd1fc8f827591bf9cb53553c47a3202020509100a020efd6001c9bb42af2b346910e0f49a172cc71741312e73cb8a81ae89a537d53d19dcb76ea4d5ac21cb206f70062a7e729f924a8568116438435ed4fcf505d6cf342006409652fcb54b0c256f30ce6abfc4785638fe8fb6ff75e18da37396ce770f917f25296c813c1b529d34aab9b9331c7e01f4b68244746c6fd627f7c208055488f1ed882a20a6b3aab5512a27542987ea6170b3c9ce335a66281c967c8990952b9fecb9c7e030526f33bcf15091d5a678ba5b761bcafbde66b11012e8eba43a32a2164db9043f98aae138197b48056c414e34e5202c70ee74679eac416ac0acf844963f43c63507a728097b0c1dca3ac3b93a4ea7ee5b6c61c1b1539accf93d8595528edaf76f3cd542f6f7b9642972f7c486a6690d05eaf88f668c2185fdbf3fdf56882c1c4214a72037b2232688596397303fa687f8c50245fbc45668b169605c65823d1759a95dc66e652a494acf6074adc50424c241058b13f7c6ae6dc3abbe11"
    }


Inputs can be seen by decoding the tx hex, the input for an anon tx is obfuscated with a ring signature:

    export TXHEX_PLAIN=$(PART_CLI -rpcwallet=receive gettransaction $TXID_PLAIN | jq -r .hex)
    export TXHEX_BLIND=$(PART_CLI -rpcwallet=receive gettransaction $TXID_BLIND | jq -r .hex)
    export TXHEX_ANON=$(PART_CLI -rpcwallet=receive gettransaction $TXID_ANON | jq -r .hex)

    PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_PLAIN | jq -r .vin[0]
    {
      "txid": "1447b3122383c9a6ec9d6b6ecca4bd7434e2a68a89a478bad074da8039d3f7fd",
      "vout": 1,
      "scriptSig": {
        "asm": "",
        "hex": ""
      },
      "txinwitness": [
        "304402205727003e9e95cd554fe8d7777132c10f252f43de702780222044771fdf7a0a0002202e1bf21a7b7d82f47690eee59940705e3c384d6d99352b9810ef849b48cdec9101",
        "0256f1892886fac8fb0dc67c10cdb7eba57beb1161fd4376d42e5637cb3dacefd6"
      ],
      "sequence": 4294967294
    }

    PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_BLIND | jq -r .vin[0]
    {
      "txid": "a934d24597405452d2423fefe81b1ca4d3715b6c072affb502c2f0b97eb340fc",
      "vout": 1,
      "scriptSig": {
        "asm": "",
        "hex": ""
      },
      "txinwitness": [
        "3044022028f0f4f92964957c96322dbd76c60e30ac0644b599f7fa35f91dc605cd8a28c702203d49518e71ae984838a4074cfb92089969e1c4e5d91b9f1d7e910ad6ac91278301",
        "03baa1fa0f4dfb94d5125c026cd2cb9813aca96bc98911c5e1acf81888896a58bd"
      ],
      "sequence": 4294967294
    }

    PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_ANON | jq -r .vin[0]
    {
      "type": "anon",
      "num_inputs": 1,
      "ring_size": 5,
      "txinwitness": [
        "09100a020e",
        "c9bb42af2b346910e0f49a172cc71741312e73cb8a81ae89a537d53d19dcb76ea4d5ac21cb206f70062a7e729f924a8568116438435ed4fcf505d6cf342006409652fcb54b0c256f30ce6abfc4785638fe8fb6ff75e18da37396ce770f917f25296c813c1b529d34aab9b9331c7e01f4b68244746c6fd627f7c208055488f1ed882a20a6b3aab5512a27542987ea6170b3c9ce335a66281c967c8990952b9fecb9c7e030526f33bcf15091d5a678ba5b761bcafbde66b11012e8eba43a32a2164db9043f98aae138197b48056c414e34e5202c70ee74679eac416ac0acf844963f43c63507a728097b0c1dca3ac3b93a4ea7ee5b6c61c1b1539accf93d8595528edaf76f3cd542f6f7b9642972f7c486a6690d05eaf88f668c2185fdbf3fdf56882c1c4214a72037b2232688596397303fa687f8c50245fbc45668b169605c65823d1759a95dc66e652a494acf6074adc50424c241058b13f7c6ae6dc3abbe11"
      ],
      "sequence": 4294967295
    }

    export PREV_TX_PLAIN=$(PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_PLAIN | jq -r .vin[0].txid)
    export PREV_TX_BLIND=$(PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_BLIND | jq -r .vin[0].txid)

    export PREV_N_PLAIN=$(PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_PLAIN | jq -r .vin[0].vout)
    export PREV_N_BLIND=$(PART_CLI -rpcwallet=receive decoderawtransaction $TXHEX_BLIND | jq -r .vin[0].vout)


Without using the txindex the previous transactions might not be able to be found in the blockchain (without knowing which block they're in):

    PART_CLI getrawtransaction $PREV_TX_PLAIN
    No such mempool transaction. Use -txindex or provide a block hash to enable blockchain transaction queries. Use gettransaction for wallet transactions.

    PART_CLI getrawtransaction $PREV_TX_BLIND
    No such mempool transaction. Use -txindex or provide a block hash to enable blockchain transaction queries. Use gettransaction for wallet transactions.


Stop the node

    PART_CLI stop


Start the node in regtest mode with txindex active:

    ./particld --daemon --regtest --nocheckpeerheight --minstakeinterval=2 --datadir=/tmp/test1 -txindex=1


Check indices and wait for sync:

    PART_CLI getinsightinfo | jq -r .txindex
    true

    until echo $(PART_CLI getindexinfo | jq -r .txindex.synced) | grep -m 1 "true"; do echo "synced height: $(PART_CLI getindexinfo | jq -r .txindex.best_block_height)" && sleep 2 ; done


Now `getrawtransaction` should work:

    PART_CLI  getrawtransaction $PREV_TX_PLAIN true | jq -r .vout[$PREV_N_PLAIN]
    {
      "n": 1,
      "type": "standard",
      "value": 618.75024459,
      "valueSat": 61875024459,
      "scriptPubKey": {
        "asm": "OP_DUP OP_HASH160 2e7e81ddc3875372103f1ad45d4a74b2a8876c61 OP_EQUALVERIFY OP_CHECKSIG",
        "desc": "addr(pZ81pX3z6arJ6qK9BgUEAGeiq8ncjsRJ4M)#j0tve4au",
        "hex": "76a9142e7e81ddc3875372103f1ad45d4a74b2a8876c6188ac",
        "address": "pZ81pX3z6arJ6qK9BgUEAGeiq8ncjsRJ4M",
        "type": "pubkeyhash"
      }
    }

    PART_CLI  getrawtransaction $PREV_TX_BLIND true | jq -r .vout[$PREV_N_BLIND]
    {
      "n": 1,
      "type": "blind",
      "valueCommitment": "09ad8a67686766d00ec123bbc22e1b643ee52e369aac18ebcc7f334f61c4b96ed9",
      "scriptPubKey": {
        "asm": "OP_DUP OP_HASH160 2c5911e0c4baf0e90144d579dbe37af8f25174f6 OP_EQUALVERIFY OP_CHECKSIG",
        "desc": "addr(pYvfcwCq94PPsJKvAmSr1ChqPx1i8UA4Wv)#3rjjf692",
        "hex": "76a9142c5911e0c4baf0e90144d579dbe37af8f25174f688ac",
        "address": "pYvfcwCq94PPsJKvAmSr1ChqPx1i8UA4Wv",
        "type": "pubkeyhash"
      },
      "data_hex": "02d08ae6dbd38c63ab02facca3b10bc887a0979fb5df77492f1f2b7596de9d7734",
      "rangeproof": "a3179c8d55144e30160b82a018a68892125885b679d9475f630bd63bfc225ab2b20b07d77a1f8d691cabfcca44b9b6bce9651adeb2f4875847d1e1383c1286150d228b6224505b1833dc8e4b086c5755e6d0602b542e6b40b4963ba56d42a6218baac8ca30c8bbc335d633a461cb689b7852d4c39f79eb36a9b95cb30753cab19442e18e0dc488c368594831b253512a15fec7371186706cd75e784b957646ab50df657e49671af909383bfe72231e1f2433430f5b27812a79f6a87e5398f2c3ac2c4b91c5a381286d740aa9cc3b4144e6e530fc43d3e65c8109ab82af0f05ae858c84e8c6809a03ea2bd200a86c7852dcb4cf5a452c568d18ebe60bd39737df4b736ee090e548225dcf4ecdac06e3d5a0a5393e4b343cd8d94161ea44946006131b99230a060475f6a1c6fee99a3fb2e2e4be6f2e9604ee3f98275b2c55455b981bf97399bfbbfde015c1c624be528374998f13c332b8ce1316f8f43ab4c31ce55800ed158e0660855504c5d0cf8ca022811a3123c7f569c10b302454113284e88a1727c2f46f2f9338979aef285085d62d3ca3de326864b02c9574669c674df601893604b0037e5d1e41a1b3c6bb032317fb75e4b972dac3fd11a01a5346bac5ea23ca0498b8fdefddcbeef340d1a5162b9f8c420b82e578a2c429a64e4cadb44556fdaf05b35fb187158351e4d254c464a00a61a6770332a264cf95b80cb2f4cba80a2cbee7268a7a1a30c86cdbd0da7d43d908c870ef18bb5778badcb10314d977bba6e65f290a71239399cb66062e8041a485053a1c0f5dfbcc7bce2b4a48e9e490cb4708d86b98ddd4805692c11ae951a27ed5939ebe5be579b675e9fdd013ed3910dc2b8f0c00dbe677ca522e5c1679ed363b7f46186a668992a7fa7394b8495f6206e51149ce11897226316ff3abf983d7b9a66dc71e747b928626a7e0ced0"
    }


Stop the node

    PART_CLI stop
