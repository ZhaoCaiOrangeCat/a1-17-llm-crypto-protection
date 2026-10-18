# M1–M11 实验记录

阶段: full
模型: E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf
模型字节: 7359259040
GPU: NVIDIA GeForce RTX 5090, 32607 MiB, 610.88
max_tokens: 200
ignore_eos: false
知识库: fixtures/kb-corpus.jsonl sha256=3885f2434b78284becba61457df64f7158c9db7bf13c317cb8069dedd8fcaf2c
工具规格: fixtures/tools/open-meteo-forecast.yml sha256=512e29bca2afb06a088cc27fae5c6793a05e272c6404a67e3632cecb87f8516f

- PASS E1 链路: temp=16.3 docs=['cmrc-0001'] leaked=False err=
- PASS E1 密文边界: forward_hit=False kb_bytes=127242
- PASS 工具实呼: 10/10
- PASS M3 篡改: 3/3
- PASS M4 重放: 3/3
- PASS M1 请求数: 1000
- PASS M2 保护成功: 1000/1000
- PASS 知识库命中: 1000/1000
- PASS M5/M6 时延: 993/1000 ratio=0.9930 head=[51.6, 60.1, 44.3, 29.8, 29.6, 43.4, 37.3, 79.0, 44.1, 68.7, 54.8, 29.3, 56.6, 32.0, 54.8, 59.9, 74.8, 73.9, 62.7, 50.7] max=112.0
- PASS M7 换钥次数: 100
- PASS M8 换钥成功: 100/100 active=1
- PASS M9 换钥中请求: 204/204
- PASS E9 状态: decrypt_only=True retired_deny=True active_revoke=False recover=REVOKED_DENIED crash=137 kill_ver=101/101
- PASS E8 隔离: 复测 cache=True differ=True cross=TAG_FAIL opened=False loaded=24/24 corrupt=True hidden=True plain=True wrong=True
- PASS M10/M11 吊销: 8/8 t0=1792161073.9702637
- PASS 吊销后新凭据: OK
- PASS 审计链: count=3740 checkpoints=37 missing=0

时延中位数 58.8 ms，P95 90.7 ms，最大 112.0 ms。
预热不进入分母。攻击样本不进入 M1。工具实呼使用 Open-Meteo，不进入 M5 分母。

全量进程末尾第一次隔离检查时，测试令牌已超过 60 秒，缓存键接口返回过期，该项当时记为失败。隔离本身随后用有效令牌复测：两租户缓存键不同，客户端传入的 salt 不改变结果；对方数据密钥不能打开向量帧；密封知识库可重新载入 24 篇；篡改一字节后 MAC 失败；换出块文件不含标题明文，正确密钥可解开，错误密钥失败。
