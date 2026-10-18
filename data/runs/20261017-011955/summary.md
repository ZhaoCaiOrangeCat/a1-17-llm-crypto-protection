# M1–M11 实验记录

阶段: full
模型: E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf
模型字节: 7359259040
GPU: NVIDIA GeForce RTX 5090, 32607 MiB, 610.88
max_tokens: 64
ignore_eos: false
知识库: fixtures/kb-corpus.jsonl sha256=3885f2434b78284becba61457df64f7158c9db7bf13c317cb8069dedd8fcaf2c
工具规格: fixtures/tools/open-meteo-forecast.yml sha256=512e29bca2afb06a088cc27fae5c6793a05e272c6404a67e3632cecb87f8516f

- PASS E1 链路: temp=14.6 docs=['cmrc-0001'] leaked=False err=
- PASS E1 密文边界: forward_hit=False kb_bytes=971478
- PASS 细粒度授权: rotate=AUTHZ_DENY infer=AUTHZ_DENY audit=AUTHZ_DENY
- PASS 窃听与备份: wire=1724 backup_open=True backup_wrong=True
- PASS 工具实呼: 10/10
- PASS M3 篡改: server=6/6 output=True tool=True
- PASS M4 重放: 3/3
- PASS M1 请求数: 1000
- PASS M2 保护成功: 1000/1000
- PASS 知识库命中: 990/1000
- PASS M5/M6 时延: 999/1000 ratio=0.9990 head=[18.4, -33.4, -7.6, 4.6, -12.7, -36.3, 46.8, 9.2, -12.3, -36.4, -15.2, 1.1, -2.8, 19.2, 41.2, 2.9, -38.1, 29.3, -39.3, 0.8] max=83.1
- PASS KV槽: bytes=57555304 chunks=220 restored=True
- PASS M7 换钥次数: 100
- PASS M8 换钥成功: 100/100 active=1
- PASS M9 换钥中请求: 204/204
- PASS E9 状态: decrypt_only=True retired_deny=True active_revoke=False recover=REVOKED_DENIED crash=137 kill_ver=101/101
- PASS E8 隔离: cache=True differ=True loaded=24/24 corrupt=True hidden=True temp=True/True cross=TAG_FAIL err=None
- PASS M10/M11 吊销: 30/30 t0=1792172665.8927703
- PASS 吊销后新凭据: OK
- PASS 审计链: count=4980 checkpoints=49 missing=0

时延中位数 -8.4 ms，P95 36.3 ms，最大 83.1 ms。
预热不进入分母。攻击样本不进入 M1。1000 次请求都带加密的工具参数；同一城市的实网结果在一小时内复用，避免两次广域网时延进入附加时延。本次实网调用 9 次。
