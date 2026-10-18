import sys, time
sys.path.insert(0, r"C:\Users\zhaoc\Desktop\密码\src")
from common.crypto import sm2_keypair, sm2_sign, sm2_verify
priv, pub = sm2_keypair()
sig = sm2_sign(priv, pub, b"abc")
t = time.perf_counter()
for _ in range(20):
    sm2_verify(pub, b"abc", sig)
print("verify", (time.perf_counter()-t)*1000/20)
