import sys
sys.path.insert(0, r"C:\Users\zhaoc\Desktop\密码\src")
from common.crypto import sm2_keypair, sm2_sign, sm2_verify
from common.frame import canon

priv, pub = sm2_keypair()
fail = 0
for i in range(40):
    msg = canon({"exp": 1792150000 + i, "roles": ["unwrap"], "tenant_id": "__kb", "n": i})
    sig = sm2_sign(priv, pub, msg)
    if not sm2_verify(pub, msg, sig):
        fail += 1
        print("fail", i, sig)
print("fails", fail)
