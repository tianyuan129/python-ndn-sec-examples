from Cryptodome.Hash import SHA256
from Cryptodome.Signature import DSS
from Cryptodome.PublicKey import ECC

import ndn.utils
from ndn.encoding import InterestParam, BinaryStr, FormalName, SignaturePtrs, SignatureType, Name, Component
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
from ndn.app_support.security_v2 import parse_certificate
from ndn.app import NDNApp

app = NDNApp()
async def main():
    try:
        timestamp = ndn.utils.timestamp()
        name = Name.from_str('/example/testApp/randomData') + [Component.from_timestamp(timestamp)]
        print(f'Sending Interest {Name.to_str(name)}, {InterestParam(must_be_fresh=True, lifetime=6000)}')
        # set a validator when requesting data
        data_name, meta_info, content = await app.express_interest(
            name, must_be_fresh=True, can_be_prefix=False, lifetime=6000, validator=verify_ecdsa_signature)

        print(f'Received Data Name: {Name.to_str(data_name)}')
        print(meta_info)
        print(bytes(content) if content else None)
    except InterestNack as e:
        print(f'Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'Timeout')
    except InterestCanceled:
        print(f'Canceled')
    except ValidationFailure:
        print(f'Data failed to validate')
    finally:
        app.shutdown()

"""
This validator parses the key name from the signature info, then express interest to fetch corresponding certificates.

Certificate itself is a Data packet, TLV format specified in https://named-data.net/doc/ndn-cxx/current/specs/certificate-format.html
Certificate content is an entity's public key, this validator extracts the public key from certificate and verify the original Data 
packet's signature.

Note: Completely validating a Data packet includes three steps:
      1. Validating the signing idenity is authorized to produce this Data packet.
         We refer this as trust schema, determined by app
      2. Verifying if the Data signature by signing identity's public key
      3. Verifying signing identity's certificate against its issuer's public key.
         Validator should recursively does this until reach to its trust anchor.
      This validator only does step 2.
"""
async def verify_ecdsa_signature(name: FormalName, sig: SignaturePtrs) -> bool:
    sig_info = sig.signature_info
    covered_part = sig.signature_covered_part
    sig_value = sig.signature_value_buf
    if not sig_info or sig_info.signature_type != SignatureType.SHA256_WITH_ECDSA:
        return False
    if not covered_part or not sig_value:
        return False
    key_name = sig_info.key_locator.name[0:]
    print('Extract key_name: ', Name.to_str(key_name))
    print(f'Sending Interest {Name.to_str(key_name)}, {InterestParam(must_be_fresh=True, lifetime=6000)}')
    cert_name, meta_info, content, raw_packet = await app.express_interest(key_name, must_be_fresh=True, can_be_prefix=True, 
                                        lifetime=6000, need_raw_packet=True)
    print('Fetched certificate name: ', Name.to_str(cert_name))
    # certificate itself is a Data packet
    cert = parse_certificate(raw_packet)
    # load public key from the data content
    key_bits = None
    try:
        key_bits = bytes(content)
    except (KeyError, AttributeError):
        print('Cannot load pub key from received certificate')
        return False
    pk = ECC.import_key(key_bits)
    verifier = DSS.new(pk, 'fips-186-3', 'der')
    sha256_hash = SHA256.new()
    for blk in covered_part:
        sha256_hash.update(blk)
    try:
        verifier.verify(sha256_hash, bytes(sig_value))
    except ValueError:
        return False
    return True

if __name__ == '__main__':
    app.run_forever(after_start=main())