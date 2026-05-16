/** 语音管道类型 — 阶段 9 启用 */

export interface TTSConfig {
  provider: 'elevenlabs' | 'edge' | 'cosyvoice';
  voiceId: string;
  rate: number;      // 0.5 - 2.0
  pitch: number;     // -20 - 20 (semitone)
}

export interface STTConfig {
  provider: 'webspeech' | 'whisper';
  language: string;
}

export interface VoiceState {
  ttsEnabled: boolean;
  sttEnabled: boolean;
  isSpeaking: boolean;
  isListening: boolean;
  ttsConfig: TTSConfig;
  sttConfig: STTConfig;
}
