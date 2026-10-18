# M1–M11 实验记录

阶段: probe
模型: E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf
模型字节: 7359259040
GPU: NVIDIA GeForce RTX 5090, 32607 MiB, 610.88
max_tokens: 64
ignore_eos: false
知识库: fixtures/kb-corpus.jsonl sha256=3885f2434b78284becba61457df64f7158c9db7bf13c317cb8069dedd8fcaf2c
工具规格: fixtures/tools/open-meteo-forecast.yml sha256=512e29bca2afb06a088cc27fae5c6793a05e272c6404a67e3632cecb87f8516f

- PASS E1 链路: temp=14.3 docs=['cmrc-0001'] leaked=False err=
- PASS E1 密文边界: forward_hit=False kb_bytes=971478
- PASS 细粒度授权: rotate=AUTHZ_DENY infer=AUTHZ_DENY audit=AUTHZ_DENY
- PASS 窃听与备份: wire=1724 backup_open=True backup_wrong=True
- PASS 工具实呼: 1/1
- PASS M3 篡改: server=6/6 output=True
- PASS M4 重放: 3/3
- PASS M1 请求数: 30
- PASS M2 保护成功: 30/30
- PASS 知识库命中: 30/30
- PASS M5/M6 时延: 29/30 ratio=0.9667 head=[65.8, 67.7, 34.4, 86.8, 31.4, 1.4, 54.0, 33.4, 26.4, 76.2, 83.9, 44.8, 61.3, 24.4, 83.3, 106.8, 55.7, 67.2, 60.9, 46.4] max=106.8
- PASS KV槽: bytes=57747056 restored=True
- PASS M7 换钥次数: 5
- PASS M8 换钥成功: 5/5 active=1
- PASS M9 换钥中请求: 16/16
- PASS E9 状态: decrypt_only=True retired_deny=True active_revoke=False recover=REVOKED_DENIED crash=137 kill_ver=6/6
- PASS E8 隔离: cache=True differ=True loaded=24/24 corrupt=True hidden=True wrong=True cross=TAG_FAIL err=None
- PASS M10/M11 吊销: 3/3 t0=1792167279.3622768
- PASS 吊销后新凭据: OK
- PASS 审计链: count=240 checkpoints=2 missing=0

时延中位数 58.3 ms，P95 90.7 ms，最大 106.8 ms。
预热不进入分母。攻击样本不进入 M1。工具实呼使用 Open-Meteo，不进入 M5 分母。
