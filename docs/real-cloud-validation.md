# 真实阿里云端到端验证（非 mock）

这份指南验证真实日本语音 → 百炼流式 ASR → 阿里云机器翻译 → 浏览器字幕。
单元测试中的 fake/stub 只验证异常回归，不代表真实云服务验证通过。

## 1. 准备账号与两套凭证

### 百炼实时 ASR

1. 登录阿里云百炼控制台，完成账号/服务开通，并确认账户可正常按量调用。
2. 选择 **华北 2（北京）**。当前项目也支持 `ap-southeast-1`（新加坡），但 API Key、Workspace ID 与模型可用地域必须一致。
3. 在目标业务空间创建 API Key，允许访问 `qwen-audio-3.0-asr-flash-streaming`。若限制了调用 IP，需允许本机当前公网出口 IP。
4. 复制同一业务空间的 Workspace ID（控制台右上角业务空间信息）。它不是 App ID、主账号 UID，也不是 RAM AccessKey ID。
5. 本项目使用业务空间专属地址：

   ```text
   wss://<Workspace DNS label>.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference
   ```

   若复制的 ID 是 `ws-….cn` 形式，适配器保留配置原值，但构造北京
   ASR 域名时移除尾部 `.cn`，避免生成多一层 DNS label、导致 TLS 证书
   主机名不匹配。不会通过关闭证书校验来绕过错误；该形式不用于新加坡地域。

### 机器翻译通用版

1. 主账号在机器翻译控制台开通 **机器翻译通用版**，确认无欠费且有可用额度。
2. 创建专用 RAM 用户，允许 OpenAPI 调用，取得 AccessKey ID 和 AccessKey Secret。
3. 为该 RAM 用户授予调用 `alimt:TranslateGeneral` 的权限。推荐最小权限自定义策略：

   ```json
   {
     "Version": "1",
     "Statement": [{
       "Effect": "Allow",
       "Action": "alimt:TranslateGeneral",
       "Resource": "*"
     }]
   }
   ```

   `AliyunMTFullAccess` 也能完成验证，但包含整个机器翻译产品的管理权限，不是最小权限，不建议长期用于本地测试。
4. 本项目使用 `mt.cn-hangzhou.aliyuncs.com`，`Scene=general`，语言代码 `ja → zh`。

**两套凭证不能互换。** 百炼用 API Key（通常以 `sk-` 开头）；机器翻译用 RAM AccessKey ID / Secret。
不要把凭证写进 Extension、提交 Git、发送到聊天或截进日志截图。

## 2. 配置网关

需要 Python 3.11+ 和 Chrome/Edge 116+（建议当前稳定版）。Extension 不需要 Node 构建。

```bash
cd services/gateway
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
# 仅首次创建；不要覆盖已经配置的 .env
[ -f .env ] || cp .env.example .env
chmod 600 .env
```

若本机 pip 私有源需要认证，且本项目不需要该源：

```bash
PIP_CONFIG_FILE=/dev/null PIP_INDEX_URL=https://pypi.org/simple \
  python -m pip install -e '.[dev]'
```

在编辑器中修改 `services/gateway/.env`：

```dotenv
VEILSUB_SPEECH_PROVIDER=aliyun
VEILSUB_TRANSLATION_PROVIDER=aliyun

DASHSCOPE_API_KEY=<你的百炼 API Key>
ALIYUN_BAILIAN_WORKSPACE_ID=<同一地域、同一业务空间的 Workspace ID>
ALIYUN_BAILIAN_REGION=cn-beijing
ALIYUN_ASR_MODEL=qwen-audio-3.0-asr-flash-streaming

ALIBABA_CLOUD_ACCESS_KEY_ID=<专用 RAM 用户的 AccessKey ID>
ALIBABA_CLOUD_ACCESS_KEY_SECRET=<对应的 AccessKey Secret>
ALIYUN_MT_ENDPOINT=mt.cn-hangzhou.aliyuncs.com
```

`<...>` 必须替换，不能原样保留。其他选项先保持 `.env.example` 默认值，不要一开始就调整 VAD/hotwords。

- `.env` 相对于进程工作目录读取，因此必须从 `services/gateway` 启动。
- shell 已导出的同名环境变量优先于 `.env`；若仍出现 mock，请检查旧环境变量。
- 修改 `.env` 后 **重启网关**，不要假定 `--reload` 一定会重新加载 `.env`；Settings 有进程缓存。
- 只验证日语识别时可以暂设 `VEILSUB_TRANSLATION_PROVIDER=none` 并使用下文 `--asr-only`，这仍是真实 ASR，不是 mock。

## 3. 先验证 Gateway，再验证 Extension

本机 8000 可能已被其他程序占用，本指南统一使用 **8010**：

```bash
# 终端 A，工作目录 services/gateway，venv 已激活
uvicorn app.main:app --host 127.0.0.1 --port 8010
```

```bash
# 终端 B
curl --fail http://127.0.0.1:8010/health
```

返回 `{"status":"ok"}` **只证明网关进程可用，不证明云端认证/模型/翻译成功**。

### 无网络的配置检查

```bash
# 终端 B，工作目录 services/gateway，venv 已激活
python scripts/cloud_smoke.py --check-config
```

检查 provider 选择及凭证是否缺失，不打印凭证，也不发送云请求。

### 有真实语音的云 Smoke Test

准备一段 **10–30 秒**、台词明确且你有权使用的日语语音（自录或已有合法录音），使用音频编辑器导出：

- WAV 容器，未压缩 PCM；
- signed 16-bit little-endian；
- 16000 Hz；
- 单声道；
- 最长 60 秒（脚本防止误上传长录音）。

不要用空字节/纯静音当成功样本，也不要将 MP3 改后缀伪装成 WAV。
脚本会按约 100ms/帧、实时速度发送音频，而非一次性灌入文件。

```bash
python scripts/cloud_smoke.py \
  --url ws://127.0.0.1:8010/v1/live \
  --audio /absolute/path/japanese-16k-mono.wav \
  --allow-paid
```

只验证 ASR：

```bash
python scripts/cloud_smoke.py --asr-only \
  --audio /absolute/path/japanese-16k-mono.wav --allow-paid
```

`--allow-paid` 是显式的计费请求许可；脚本本身不会在安装、配置检查或 CI 中自动调用云服务。
如需保留证据，手工将输出保存到仓库外的私有目录；输出包含原文/译文，不应随意公开。

完整通过标准：

1. `session.ready` 中服务端确认 `speech_provider=aliyun` 和 `translation_provider=aliyun`；
2. 收到至少一条非空 `subtitle.final` 日语原文；
3. 收到 `subtitle.translation` 中文译文，`id + revision` 对应已有 final；
4. 收到 `session.stopped` 和 metrics，无 `session.error`；
5. 脚本返回退出码 0 并打印 `PASS`；
6. 人工对照录音，确认原文不是幻觉、译文表达正确。

`session.ready` 不是云任务已认证的充分证据：SDK worker 启动后，云端仍可能异步返回认证错误。
`PASS` 只说明真实调用链和终止流程通过，**不等于识别准确率/翻译质量达标**。

## 4. 真实浏览器验证

1. 打开 `chrome://extensions`（Edge 为 `edge://extensions`），开启开发者模式。
2. 点击“加载已解压的扩展程序”，选择仓库 `apps/extension` 目录。
3. 打开一个普通 HTTP/HTTPS 页面的日语视频/音频，手动点击播放。先用清晰人声、低背景音乐、10–30 秒内容。
4. Popup 的 Gateway 设为 `ws://127.0.0.1:8010/v1/live`，Source `ja-JP`，Target `zh-CN`，Display `Bilingual`，delay `0`。
5. 点击 Start，确认原声音仍可听见，日语 interim/final 出现，中文随后更新同一行。
6. 点击 Stop，确认捕获指示结束、原音正常、字幕不再恢复显示，重新打开 Popup 能看到 Last session metrics。

排错入口：Gateway 终端、扩展详情中的 Service Worker、offscreen document 的 DevTools。不要复制包含密钥的日志/网络鉴权头。

### 修复后的重点回归

- 正常页面连续 Start/Stop 5 次，每次应只有一个活跃 capture/socket；
- 在 Connecting 时立刻 Stop：不能后来又变为 Capturing/Reconnecting；
- Stop 后立刻再 Start：旧字幕/PCM/错误不能污染新会话；
- 在 Reconnecting 退避期间 Stop 后再 Start：不能残留旧重连循环；
- 实时调节样式，进入/退出原生 fullscreen，字幕仍可见；
- 设置 3000ms delay 后 Stop：不能 3 秒后又弹出字幕；
- 关闭 captured tab，切到别的 tab 后 Stop，Extension reload 后再 Start；
- 第二阶段再测试 5–10 分钟，最后 20–30 分钟，覆盖静音、音乐、短句；留意 reconnect/drop 和云端实际用量。

真实云调用会消耗 ASR 音频时长和 MT 字符额度；不要一开始就长时间循环跑。最权威账单在各服务控制台，不以客户端 estimated metrics 代替。

## 5. 常见失败

| 现象 | 检查项 |
| --- | --- |
| `/health` 404，WebSocket 404 | 是否连到其他服务/旧端口；检查 uvicorn bind 是否失败 |
| ASR 401/403 | API Key、Workspace ID、地域是否一致；模型权限与出口 IP 限制 |
| 模型不存在/无权限 | 控制台当前地域是否支持该模型；不要把 `qwen3-asr-flash-realtime` 直接替换到本适配器，它使用不同协议 |
| MT 10009 / AccessDenied | RAM 用户是否授予 `alimt:TranslateGeneral`；不是百炼 API Key |
| MT 10010 / 10013 | 主账号是否开通通用版、额度/余额/欠费情况 |
| 有日文没中文 | 先确认 Display 为 Bilingual、Target 为 zh-CN；Stop 后在 Last session 看 calls/failures/timeouts 与 Last translation error；网关日志记录脱敏错误。calls=0 要检查是否只有 interim；10009 是权限，10010 是服务未开通，10013 是开通/欠费，SignatureDoesNotMatch 是签名/凭证问题；timeouts 增长再测量网络和调整 timeout |
| Capturing 但无字幕 | 页面的音频是否真正播放；offscreen AudioContext 是否 running；不要用静音测试准确率 |
| 连接失败/反复重连 | 查看 Popup 的具体 `session.error`；明确会话错误默认终止捕获，网络断开最多重试 5 次且 ready 不重置预算；检查 WSS（443）DNS/TLS/代理/防火墙 |
| TLS certificate hostname mismatch | Workspace 字段是否误填域名/URL；`ws-….cn` 的命名空间尾缀应在构造北京 endpoint 时去除，不要关闭 TLS 验证 |
| 较长句子翻译失败 | TranslateGeneral 单次最多 5000 字符；查看失败/timeout计数 |

公网托管前仍需鉴权/配额/TLS，不要为本地验证把未鉴权网关绑定到 `0.0.0.0`。
DashScope 私有生命周期适配依赖已测试 SDK；异常网络情况下底层 SDK 线程并不保证立即终止。此修复保证网关本地清理有界，不声称 SDK 支持完整 transport abort。

## 官方参考

- [百炼 API Key](https://help.aliyun.com/zh/model-studio/get-api-key)
- [获取 Workspace ID](https://help.aliyun.com/zh/model-studio/obtain-the-app-id-and-workspace-id)
- [Qwen Streaming Python SDK](https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-python-sdk)
- [Qwen Streaming WebSocket 接口/地域](https://help.aliyun.com/zh/model-studio/fun-asr-realtime-websocket-api)
- [机器翻译服务开通](https://help.aliyun.com/zh/machine-translation/getting-started/activate-machine-translation-for-developers)
- [RAM 授权](https://help.aliyun.com/zh/machine-translation/getting-started/ram-user-authorization)
- [TranslateGeneral](https://help.aliyun.com/zh/machine-translation/developer-reference/api-alimt-2018-10-12-translategeneral)
