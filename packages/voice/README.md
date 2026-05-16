"""昔涟语音管道 — 远期计划

当前状态：接口占位，不实现。

## 规划

### TTS 输出（优先）
- 集成 ElevenLabs / Edge TTS / 阿里 CosyVoice
- marker_parser.py 的 markers_to_ssml() 作为 SSML 生成入口
- 3 种标记已预留映射：
  - [pause:Xs]   → <break time="Xs"/>
  - [emph:text]  → <emphasis level="moderate">text</emphasis>
  - [whisper:text] → <prosody volume="soft" rate="slow">text</prosody>

### STT 输入（后做）
- Web Speech API（浏览器端免费）
- 或阿里云 NLS / OpenAI Whisper

### 全双工（远期）
- VAD 检测静音自动结束
- 可打断、可同时说

## 接入点
- MarkerParser.markers_to_ssml() — SSML 转换（packages/shared/marker_parser.py）
- types/voice.ts — 前端类型定义
- HTTP 路由注释占位 — gateway/channels/http_channel.py
"""
