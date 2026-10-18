# 小规模实验记录

模型: E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf
样本: 5

- PASS E1 链路: result=OK temp=16.1 place=北京 docs=['cmrc-0018'] leaked=False out='资料未提及泡泡战士，北京当前气温为16.1℃。\n(注：资料中“冰雪皇后”与“泡泡'
- PASS E1 密文边界: forward_hit=False kb_bytes=124036
- PASS E2 连续保护: 5/5
- PASS E3 时延: 20/20 delta_ms=[37.0, 20.0, 44.3, 20.5, 24.5, 52.2, 41.6, 18.1, 44.9, 22.7, 19.3, 68.9, 50.2, 59.6, 31.7, 4.8, 30.9, 35.3, 52.1, 27.5]
- PASS E4 篡改: identified=2/2 audit=2 ct=TAG_FAIL mac=TAG_FAIL
- PASS E5 重放: first=OK second=REPLAY window=WINDOW
- PASS E6 换钥: rotate=5/5 active=1 inflight=3/3
- PASS E7 吊销: denied=3/3 t0=1792156528.5827003
- PASS E8 隔离: cache_differ=True cross=TAG_FAIL deny=AUTHZ_DENY
- PASS E9 状态: active=1 revoke=True recover=REVOKED_DENIED
- PASS 审计链: count=36

全量 1000 次未执行。
