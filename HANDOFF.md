# 交接说明

这份文档给没有参加过先前对话的人使用。先读完第 1 节和第 2 节，再读代码。不要根据目录名自己挑选一份日志当正式成绩。

项目是密码竞赛 A1-17「大模型推理数据全流程密码保护方案」的原型和已闭环实验。工作目录是 `C:\Users\zhaoc\Desktop\密码`。同一份快照在私有仓库 https://github.com/ZhaoCaiOrangeCat/a1-17-llm-crypto-protection 。桌面上的 `a1-17-submit` 是该仓库的本地克隆。

没有用户明确要求时，不要重跑 1000 对，不要覆盖 `data/raw/` 和 `data/runs/`，不要改 `fixtures/assets.json` 的哈希，不要动端口 8088。

## 1. 正式成绩只认这些文件

功能、攻击、换钥、吊销的正式记录是 9B 全量：

- `data/reports/summary.md`
- `data/runs/20261017-011955/`（`m1.jsonl`、`m5.jsonl`、`m7.jsonl`、`m11.jsonl`、`chain.jsonl`、`run.log`）
- `data/raw/` 里的 `m1.jsonl`、`m5.jsonl`、`m7.jsonl`、`m11.jsonl` 是从上面这个目录恢复回去的

| 指标 | 结果 |
| --- | --- |
| M1 / M2 连续推理、保护成功 | 1000/1000 |
| M3 预置篡改 | 服务端 6/6，输出和工具参数也识别 |
| M4 预置重放 | 3/3 |
| M7 / M8 在线换钥 | 100 次，100/100 成功 |
| M9 换钥过程中的合法请求 | 204/204。这个数是整批合计，被抄到了每一行上，不是每次轮换各 204 条 |
| M10 / M11 吊销 | 30/30，约 t0+1.0 s 到 t0+58.1 s，错误码 `AUTH_REVOKED` |
| 审计链 | 4980 行，断链 0，检查点 49。节点计数约为 kb 1246、tool 1238、sidecar 1244、gateway 1252 |
| 知识库命中 | 990/1000。这不是赛题门限 |
| KV 槽密封 | 57,555,304 字节，220 个分块，还原成功 |

时延的正式记录不是上面那份 summary。summary 里的「中位数 −8.4 ms、999/1000」来自先关后开：保护总是第二次调用，占了预热的便宜。引用时延时用两种顺序抵消后的 9B 结果：

- `data/logs/balanced.log`
- `data/raw/m5-balanced.jsonl`

| 项 | 9B 抵消后 |
| --- | --- |
| 无保护平均 | 483.5 ms |
| 加保护平均 | 503.5 ms |
| 先关后开平均差 | −8.7 ms |
| 先开后关平均差 | +48.6 ms |
| 抵消后平均附加时延 | 19.9 ms |
| 合格 | 993/1000 |

合格规则是赛题原文：Δ ≤ 30 ms，或 Δ ≤ 无保护时延的 15%。方案里如果出现「95% 的 Δ ≤ 30 ms」，那是内部愿望，9B 抵消后没有达到，也不要写成赛题要求。

测量方法：每条提示词连续四次，顺序固定为无关、加保护、再加保护、再无关。先关后开 = 第 2 次减第 1 次。先开后关 = 第 3 次减第 4 次。抵消后 = 这两个差的平均。预热 10 条丢掉。通过条件用抵消后的 Δ。

## 2. 不要这样讲

- 不要说加保护比不加保护更快。先关后开的负数是顺序造成的。
- 不要把「全流程」说成创新。全流程是赛题要求。已经实现、可以讲的只有三件：热路径只用短帧，槽位密封放在请求返回之后；请求绑定 `key_ver`，吊销后旧密钥不能恢复，旧凭据在 60 秒内拒绝；缓存键里的盐来自服务端，忽略客户端自己带的盐。
- 不要写成优于 TEE、同态推理或阿里云密态 RAG。那些保护的是另一类对手。本原型防的是链路窃听、篡改、重放和跨租户。
- 不要把 27B 的数字替换 9B。27B 是鲁棒性补充。
- 纯 SM4/HMAC 微基准中位数约 17 ms（`tests/bench_crypto.py`）。9B 抵消后的 19.9 ms 接近这个量级。27B 抵消后的 90 ms 大于微基准，因为两种顺序不对称，里面有运行时差异，不是 SM4 变慢了 90 ms。

## 3. 补充实验

这些都不替代第 1 节的 9B 正式成绩。

| 实验 | 结果 | 文件 |
| --- | --- | --- |
| 27B 全量，同一套四次调用 | 无保护 1239.3 ms，加保护 1329.2 ms，先关后开 +123.7 ms，先开后关 +56.3 ms，抵消后 90.0 ms，1000/1000。全部 Δ > 30 ms，靠 15% 规则通过。最大 152.3 ms | `data/logs/balanced-27b-1000.log`，`data/raw/m5-balanced-27b-1000.jsonl`，`data/runs/27b-balanced-20261017-202434/` |
| 27B 的第 689 条 | 全量中一次 4372 ms 停顿被丢掉。随后重测，Δ 40.0 ms，合格后插回。重测前 999 条在同一运行目录的 `m5-balanced-27b-999-before-retry.jsonl` | 同上 |
| 27B 的 20 条试点 | 抵消后 80.6 ms，20/20 | `data/logs/balanced-27b.log`，`data/raw/m5-balanced-27b.jsonl` |
| 长提示词 8 条 | 无保护 1181.2 ms，加保护 1251.0 ms，Δ 69.8 ms，8/8 | `data/logs/long-samples.log`，`data/raw/long-samples.jsonl` |
| 三城工具调用 6 条 | 无保护 853.5 ms，加保护 911.9 ms，Δ 58.5 ms，6/6。模型在 131 token 左右停下，这组没有稳定超过 1 秒 | 同上 |
| 伪造凭据、篡改已缓存令牌、对象类型、嗅探 | 全部拒绝或报文中看不到明文。嗅探的是侧车收到的 HTTP 正文，不是网卡抓包 | `data/logs/threat-extra.log`，`data/raw/threat-extra.jsonl` |
| 奇偶交替在 100 对处停止 | 先关后开 50/50、平均差 −9.3 ms；先开后关 3/50、平均差 +109.4 ms。这是顺序效应，不是成绩 | `data/runs/20261017-alternating-100/` |
| 两种模型的时延图 | 上排来自两份 1000 对原始记录，下排四次拆分是各 6 条样本 | `data/reports/latency-9b-27b.png`，脚本 `tests/plot_latency_orders.py` |

`data/runs/` 里还有多次中途失败或被停掉的 `run.log`。没有写进上表的，都不要当成成绩。

9B 四次拆分（6 条，非正式 1000）里，第一次预填充约 68 ms，后三次约 28 ms，解码四次都约 440 ms。所以第一次加保护几乎被预填充下降抵消，先关后开只有约 +5 ms，先开后关约 +51 ms。27B 另一次 4 条核对里，预填充四次都约 170 ms，解码都约 1030 ms，没有这 40 ms 可抵，第一次加保护反而更慢。这些拆分数字写在作图脚本的常量里，没有单独的 jsonl。

## 4. 系统在做什么

一条本机推理链：终端、网关、知识库、工具代理、模型侧车、审计、密钥库。模型进程是外部的 `llama-server`，原型不改它。GPU 上正在使用的 KV 保持明文。离开进程的提示词、检索、工具参数、输出、换出块和备份按帧做 SM4-CTR 和 HMAC-SM3。

端口只监听 127.0.0.1：

| 服务 | 端口 |
| --- | --- |
| 密钥库 | 8711 |
| 网关 | 8712 |
| 知识库 | 8713 |
| 工具代理 | 8714 |
| 模型侧车 | 8715 |
| 审计 | 8716 |
| llama-server | 18080 |

8088 是用户别的服务，不要占用，也不要结束。

`src/runtime.py` 的 `boot()` 会先校验 `fixtures/assets.json`，然后清空 `var/`。主密钥、SM2 身份和会话密钥每次启动重新生成，写到 `var/keys/dev.json` 和 `var/kms.sqlite`。所以密钥目录没有进 Git。读代码时不要去仓库里找一份固定私钥。

租户：`tenant-a`、`tenant-b` 只有 `infer`。`admin` 有 `key_rotate`、`key_revoke`、`audit_read`，不能推理。`__kb`、`__tool`、`__sidecar` 只有 `unwrap`。用户凭据 TTL 60 秒，服务身份 TTL 3600 秒。

算法在 `src/common/crypto.py` 和 `src/common/frame.py`。身份是 SM2。摘要和审计链是 SM3。帧加密是 SM4-CTR，完整性是 HMAC-SM3，密钥导出是 SM3。帧魔数 `A117`。对象类型：prompt=1，query=2，retrieval=3，vector=4，output=5，tool_arg=6，tool_result=7，kv_block=8，audit=9，archive=10。关联数据绑版本、对象类型、`key_ver`、时间、租户、`req_id`、随机数。网关要求帧的对象类型和槽位名称一致，不一致返回 `AUTHZ_DENY`。

密钥层次：主密钥包租户 KEK，KEK 包请求 DEK。KEK 状态有 PreActive、Active、DecryptOnly、Retired、Revoked，同时只有一个 Active。写用 Active，读先 Active 再 DecryptOnly。轮换是一次 sqlite 事务：新版本变 Active，旧 Active 变 DecryptOnly，写指针指向新版本。`tests/crash_rotate.py` 在提交前杀进程，版本不前进。吊销后的 KEK 不能解出，错误 `REVOKED_DENIED`。

令牌验签缓存绑的是 `SM3(规范声明 || 签名)`，不是只绑 `jti`。吊销每次都查库。这是为了堵住「缓存过 jti 之后改声明仍能通过」。

热路径不做逐 token 的 GPU KV 加密。知识库检索 k=1，正文截到 80 字。工具结果按城市缓存 3600 秒；9B 那次 1000 对里实网调用是 9 次，其余是缓存。审计哈希在请求线程里就算好返回，落盘和 SM2 检查点在写线程里做。审计记录没有提示词和输出正文字段。

缓存键是 `SM3(租户 || 服务端盐 || SM3(提示词))`。盐在密钥库，客户端带来的盐不算数。

## 5. 数据和环境

知识库是 CMRC 2018 trial，24 篇，本地 `fixtures/kb-corpus.jsonl`，sha256 `3885f2434b78284becba61457df64f7158c9db7bf13c317cb8069dedd8fcaf2c`。排序只有余弦。标题在特征文本里重复 3 次，没有加分。检索在内存中的解密语料上做，不是密文上搜索。

工具是 Open-Meteo。规格 `fixtures/tools/open-meteo-forecast.yml`，sha256 `512e29bca2afb06a088cc27fae5c6793a05e272c6404a67e3632cecb87f8516f`。提示词 `fixtures/prompts-1000.jsonl`，sha256 `d22682b5730ad460ec778eceb86ab6f49a8dc3c38ed2d8463540198ec97625b3`。`get_weather.json` 713 字节，sha256 `c22e2b4b625f505307289722de816819de068d656e212eb243480ef357e48ed2`。运行时不重新下载。哈希不符，`boot()` 直接拒绝。

正式模型是 9B：`E:\AI\models\llm\gguf\Qwen3.5-9B-abliterated\Qwen3.5-9B-abliterated-Q6_K.gguf`，7,359,259,040 字节，别名 `qwen3.5-9b`。补充模型是 27B：`E:\AI\models\llm\gguf\Qwen3.8-27B\Qwen3.8-27B-UD-Q5_K_XL.gguf`，别名 `qwen3.8-27b`。推理程序 `E:\qwen agent\llama-server.exe`。GPU 是 RTX 5090，32 GB 这一档。不要用 WSL，也不要接 `E:\qwen agent` 里那个局域网聊天代理。

Python 用 `C:\Users\zhaoc\Desktop\密码\.venv\Scripts\python.exe`。依赖在 `env/requirements.txt`：`gmssl==3.2.2`、`pycryptodomex==3.24.1`。作图另外用了 matplotlib，不在这份依赖里。Windows 命令不要用 PowerShell 5.1 的 `$_` 和 `&&`。

`src/sidecar/server.py` 里 `LLAMA_MAX_TOKENS = 64`，`ignore_eos` 为假。方案文档仍写着 32，以代码和 `summary.md` 的 64 为准。

今天若执行 `tests/run_m1_m11.py` 里的 `ensure_llama()`，它会按该文件当前的 `LLAMA_ARGS` 启动 9B：相似度阈值 0.5，带 `--cache-ram 2048`，没有 `--no-cache-prompt`。27B 脚本 `start_27b()` 用的是另一组参数：`--no-cache-prompt`，相似度阈值 0。`data/logs/llama.cmdline` 是后来一次 9B 重启写下的，不能当作更早那次 1000 对的启动证明。

## 6. 代码和脚本怎么对应

| 路径 | 作用 |
| --- | --- |
| `src/runtime.py` | 启动并清空 `var/` |
| `src/gateway/server.py` | 鉴权、转发知识库、工具和侧车。数据面是 HTTP 密文，不是进程内直接调用 |
| `src/kms/` | 注册、签发 DEK、轮换、吊销 |
| `src/kb/server.py` | 密封语料、余弦检索 |
| `src/toolproxy/server.py` | Open-Meteo，按城市缓存 |
| `src/sidecar/server.py` | 解密、调用 llama、密封输出 |
| `src/audit/server.py` | SM3 哈希链 |
| `src/client.py` | 终端。计时包住整次调用；保护模式下签发 DEK 在计时内，`ensure()` 在计时外 |
| `tests/run_m1_m11.py` | M1–M11 套件。当前代码对偶数条先关后开、奇数条先开后关，并会用写模式打开 `data/raw/m1.jsonl` 和 `m5.jsonl`。不要为了「再确认一次」去跑它 |
| `tests/run_balanced.py` | 9B 时延正式测量 |
| `tests/run_balanced_27b.py` | 27B 时延补充 |
| `tests/run_long_samples.py` | 长提示词和多工具 |
| `tests/run_threat_extra.py` | 伪造身份、对象类型、嗅探 |
| `tests/crash_rotate.py` | 轮换提交前崩溃 |
| `tests/seal_slot.py` | 分块密封已有 KV 槽 |
| `tests/bench_crypto.py` | 只测密码，不测模型 |
| `A1-17-方案与实验大纲.md` | 设计说明。指标表和威胁范围可以读。`max_tokens`、27B 只做 20 次、以及部分实现细节已经落后于代码 |

保护成功的六条，以方案 1.3 为准：验签且未吊销、重放检查、授权、侧车解开提示词/检索/工具参数并验完整性、终端验输出完整性、审计链衔接。任一条失败即这次保护失败。

## 7. 边界

这些是当前实现的边界，写报告时要承认，不要补作已经完成：

- 能读到进程内存或 `var/kms.sqlite` 的人可以拿到主密钥和签名私钥。密钥库不是 HSM。
- GPU 里的 KV 是明文。槽位密封发生在请求返回之后，而且是分块做的。不要把整槽一次性送进 SM3，曾经因此把进程打死。
- 知识库解密后整库留在内存里。检索不是在密文上做的。
- 重放随机数表只在内存里，重启后窗口重新开始。
- 只有请求带 `spill=True` 才把提示词封进换出块，而且用的是这一次的请求 DEK，没有单独的 `DEK_kv`。
- 审计的签名和验签在同一进程。
- 嗅探证据是侧车收到的 HTTP 正文，不是网卡抓包。

未实现、也不要写进已有结果的事项：按命中再解密语料、单独的换出密钥、持久化随机数表、额外签名。这些一旦加进 1000 对的热路径，现有时延记录就不能再当原样成绩。

## 8. 交给下一个人的动作

写报告时，功能表引用第 1 节的 9B 套件，时延表引用 `balanced.log` 的 19.9 ms 和 993/1000。27B、长提示词、多工具、伪造凭据放在补充实验。图用 `data/reports/latency-9b-27b.png`。

需要复现时，先确认 18080 没有别人的 llama-server，再用对应脚本启动模型，然后 `boot()`。不要为了核对数字而重跑 1000 对。
