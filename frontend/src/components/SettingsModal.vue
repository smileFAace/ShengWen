<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import {
  PhX,
  PhCpu,
  PhKey,
  PhFlask,
  PhSpinner,
  PhBrain,
  PhMicrophone,
  PhGitBranch,
  PhFolderOpen,
} from '@phosphor-icons/vue'
import type { LLMProvider, LLMSettings, TranscriptionSettings, SummarizationSettings } from '../types'

const props = defineProps<{
  isOpen: boolean
  llmProviders: LLMProvider[]
  llmSettings: LLMSettings | null
  isUpdatingLlmSettings: boolean
  isTestingLlm: boolean
  transcriptionSettings: TranscriptionSettings | null
  isUpdatingTranscriptionSettings: boolean
  summarizationSettings: SummarizationSettings | null
  isUpdatingSummarizationSettings: boolean
  isReadingBilibiliCookieFromBrowser: boolean
}>()

const emit = defineEmits<{
  close: []
  updateLlmSettings: [payload: {
    provider: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  }]
  testLlm: []
  updateLlmSettingsAndTest: [payload: {
    provider: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  }]
  updateTranscriptionSettings: [payload: {
    device?: 'cpu' | 'cuda'
    model_source?: 'auto_download' | 'manual_path'
    model_size?: 'tiny' | 'base' | 'small' | 'medium' | 'large'
    model_path?: string
    enable_bilibili_subtitle_fetch?: boolean
    bilibili_sessdata?: string
    clear_bilibili_sessdata?: boolean
  }]
  readBilibiliCookieFromBrowser: []
  updateSummarizationSettings: [payload: {
    chunk_target_duration_sec?: number
    chunk_min_duration_sec?: number
    chunk_max_duration_sec?: number
    boundary_jump_sec?: number
    auto_chunk_min_audio_duration_sec?: number
    auto_chunk_min_transcript_lines?: number
    max_agent_value_chars?: number
    fallback_to_standard_on_agent_error?: boolean
    transcript_dir?: string
    summary_dir?: string
  }]
}>()

const settingsTab = ref<'llm' | 'transcription' | 'summarization'>('llm')

// LLM 设置
const llmProvider = ref('')
const llmBaseUrl = ref('')
const llmModelId = ref('')
const llmTemperature = ref(0.7)
const llmApiKey = ref('')

// 转录设置
const transcriptionDevice = ref<'cpu' | 'cuda'>('cpu')
const transcriptionModelSource = ref<'auto_download' | 'manual_path'>('auto_download')
const transcriptionModelSize = ref<'tiny' | 'base' | 'small' | 'medium' | 'large'>('tiny')
const transcriptionModelPathInput = ref('')
const enableBilibiliSubtitleFetch = ref(true)
const globalBilibiliSessdataInput = ref('')

// Agent 设置
const chunkTargetDurationSec = ref(20)
const chunkMinDurationSec = ref(10)
const chunkMaxDurationSec = ref(30)
const boundaryJumpSec = ref(10)
const autoChunkMinAudioDurationSec = ref(40)
const autoChunkMinTranscriptLines = ref(1800)
const maxAgentValueChars = ref(500)
const fallbackToStandardOnAgentError = ref(true)

// 输出目录设置
const transcriptDir = ref('temp')
const summaryDir = ref('temp')

const secondsToMinutes = (seconds: number) => {
  return Math.round((Number(seconds || 0) / 60) * 10) / 10
}

const minutesToSeconds = (minutes: number) => {
  return Math.round(Number(minutes || 0) * 60)
}

const bilibiliCookieSourceLabel = computed(() => {
  const source = props.transcriptionSettings?.bilibili_cookie_source || 'none'
  if (source === 'global') return '全局配置'
  if (source === 'env') return '环境变量'
  return '未设置'
})

const requiredModelFilesLabel = computed(() => {
  const files = props.transcriptionSettings?.required_model_files || []
  if (!files.length) return 'config.json, model.bin, tokenizer.json, vocabulary.txt'
  return files.join(', ')
})

watch(() => props.llmSettings, (settings) => {
  if (settings) {
    llmProvider.value = settings.provider || ''
    llmBaseUrl.value = settings.base_url || ''
    llmModelId.value = settings.model_id || ''
    llmTemperature.value = settings.temperature ?? 0.7
    llmApiKey.value = ''
  }
}, { immediate: true })

watch(() => props.transcriptionSettings, (settings) => {
  if (settings) {
    transcriptionDevice.value = settings.device || 'cpu'
    transcriptionModelSource.value = settings.model_source || 'auto_download'
    transcriptionModelSize.value = settings.model_size || 'tiny'
    transcriptionModelPathInput.value = settings.model_path || ''
    enableBilibiliSubtitleFetch.value = settings.enable_bilibili_subtitle_fetch ?? true
  }
}, { immediate: true })

watch(() => props.summarizationSettings, (settings) => {
  if (settings) {
    chunkTargetDurationSec.value = secondsToMinutes(settings.chunk_target_duration_sec)
    chunkMinDurationSec.value = secondsToMinutes(settings.chunk_min_duration_sec)
    chunkMaxDurationSec.value = secondsToMinutes(settings.chunk_max_duration_sec)
    boundaryJumpSec.value = settings.boundary_jump_sec
    autoChunkMinAudioDurationSec.value = secondsToMinutes(settings.auto_chunk_min_audio_duration_sec)
    autoChunkMinTranscriptLines.value = settings.auto_chunk_min_transcript_lines
    maxAgentValueChars.value = settings.max_agent_value_chars
    fallbackToStandardOnAgentError.value = settings.fallback_to_standard_on_agent_error
    transcriptDir.value = settings.transcript_dir || 'temp'
    summaryDir.value = settings.summary_dir || 'temp'
  }
}, { immediate: true })

const handleProviderPresetChange = () => {
  const provider = props.llmProviders.find(p => p.id === llmProvider.value)
  if (provider) {
    llmBaseUrl.value = provider.default_base_url || ''
    llmModelId.value = provider.default_model_id || ''
  }
}

const handleSaveLlmSettings = () => {
  const payload: {
    provider: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  } = {
    provider: llmProvider.value,
    base_url: llmBaseUrl.value.trim(),
    model_id: llmModelId.value.trim(),
    temperature: llmTemperature.value,
  }

  if (llmApiKey.value.trim()) {
    payload.api_key = llmApiKey.value.trim()
  }

  emit('updateLlmSettings', payload)
  llmApiKey.value = ''
}

const handleTestLlm = () => {
  // 构建配置 payload
  const payload: {
    provider: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  } = {
    provider: llmProvider.value,
    base_url: llmBaseUrl.value.trim(),
    model_id: llmModelId.value.trim(),
    temperature: llmTemperature.value,
  }

  if (llmApiKey.value.trim()) {
    payload.api_key = llmApiKey.value.trim()
  }

  // 触发保存并测试
  emit('updateLlmSettingsAndTest', payload)

  // 清空 API Key 输入框
  llmApiKey.value = ''
}

const handleSaveTranscriptionSettings = () => {
  const payload: {
    device?: 'cpu' | 'cuda'
    model_source?: 'auto_download' | 'manual_path'
    model_size?: 'tiny' | 'base' | 'small' | 'medium' | 'large'
    model_path?: string
    enable_bilibili_subtitle_fetch?: boolean
    bilibili_sessdata?: string
  } = {
    device: transcriptionDevice.value,
    model_source: transcriptionModelSource.value,
    model_size: transcriptionModelSize.value,
    model_path: transcriptionModelPathInput.value.trim(),
    enable_bilibili_subtitle_fetch: enableBilibiliSubtitleFetch.value
  }

  const cookie = globalBilibiliSessdataInput.value.trim()
  if (cookie) {
    payload.bilibili_sessdata = cookie
  }

  emit('updateTranscriptionSettings', payload)
  globalBilibiliSessdataInput.value = ''
}

const clearGlobalBilibiliSessdata = () => {
  emit('updateTranscriptionSettings', { clear_bilibili_sessdata: true })
}

const handleReadBilibiliCookieFromBrowser = () => {
  emit('readBilibiliCookieFromBrowser')
}

const handleSaveSummarizationSettings = () => {
  emit('updateSummarizationSettings', {
    chunk_target_duration_sec: minutesToSeconds(chunkTargetDurationSec.value),
    chunk_min_duration_sec: minutesToSeconds(chunkMinDurationSec.value),
    chunk_max_duration_sec: minutesToSeconds(chunkMaxDurationSec.value),
    boundary_jump_sec: boundaryJumpSec.value,
    auto_chunk_min_audio_duration_sec: minutesToSeconds(autoChunkMinAudioDurationSec.value),
    auto_chunk_min_transcript_lines: autoChunkMinTranscriptLines.value,
    max_agent_value_chars: Math.max(100, Number(maxAgentValueChars.value || 0)),
    fallback_to_standard_on_agent_error: fallbackToStandardOnAgentError.value,
    transcript_dir: transcriptDir.value.trim() || 'temp',
    summary_dir: summaryDir.value.trim() || 'temp',
  })
}
</script>

<template>
  <!-- 遮罩层 -->
  <Transition name="modal-fade">
    <div
      v-if="isOpen"
      class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex flex-col items-center justify-center p-4 gap-4"
      @click.self="emit('close')"
    >
      <!-- 弹窗主体 -->
      <div class="bg-white rounded-2xl shadow-2xl w-full max-w-4xl h-[85vh] flex flex-col md:flex-row overflow-hidden">
        <!-- 左侧导航栏 (桌面端) / 顶部导航 (移动端) -->
        <div class="md:w-48 shrink-0 bg-slate-50 border-b md:border-b-0 md:border-r border-slate-200 flex md:flex-col py-3 md:py-6 overflow-x-auto md:overflow-x-visible">
          <nav class="flex md:flex-col flex-1 px-3 gap-1 md:space-y-1 min-w-max md:min-w-0">
            <button
              @click="settingsTab = 'llm'"
              :class="[
                'flex items-center gap-2 md:gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap',
                settingsTab === 'llm'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-slate-600 hover:bg-white/50 hover:text-slate-800'
              ]"
            >
              <PhBrain :size="18" :weight="settingsTab === 'llm' ? 'fill' : 'regular'" />
              <span>LLM 配置</span>
            </button>

            <button
              @click="settingsTab = 'transcription'"
              :class="[
                'flex items-center gap-2 md:gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap',
                settingsTab === 'transcription'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-slate-600 hover:bg-white/50 hover:text-slate-800'
              ]"
            >
              <PhMicrophone :size="18" :weight="settingsTab === 'transcription' ? 'fill' : 'regular'" />
              <span>转录设置</span>
            </button>

            <button
              @click="settingsTab = 'summarization'"
              :class="[
                'flex items-center gap-2 md:gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors whitespace-nowrap',
                settingsTab === 'summarization'
                  ? 'bg-white text-blue-600 shadow-sm'
                  : 'text-slate-600 hover:bg-white/50 hover:text-slate-800'
              ]"
            >
              <PhGitBranch :size="18" :weight="settingsTab === 'summarization' ? 'fill' : 'regular'" />
              <span>Agent 设置</span>
            </button>
          </nav>
        </div>

        <!-- 右侧内容区 -->
        <div class="flex-1 flex flex-col min-w-0 min-h-0">
          <!-- 头部栏 (仅桌面端) -->
          <div class="hidden md:flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-white">
            <h2 class="text-lg font-semibold text-slate-800">
              {{ settingsTab === 'llm' ? 'LLM 配置' : settingsTab === 'transcription' ? '转录设置' : 'Agent 设置' }}
            </h2>
            <button
              @click="emit('close')"
              class="p-2 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors"
            >
              <PhX :size="20" />
            </button>
          </div>
          <!-- 内容区 -->
          <div class="flex-1 overflow-y-auto px-4 md:px-6 py-4 md:py-6 custom-scrollbar min-h-0">
            <!-- LLM 设置 -->
            <div v-if="settingsTab === 'llm'" class="space-y-4">
              <!-- 基础配置 -->
              <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
                <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                  <PhBrain :size="18" class="text-blue-500" />
                  <h3 class="text-sm font-semibold text-slate-800">基础配置</h3>
                </div>

                <div>
                  <label class="block text-xs font-medium text-slate-700 mb-2">LLM 供应商</label>
                  <div class="relative">
                    <PhCpu :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <select
                      v-model="llmProvider"
                      :disabled="isTestingLlm || isUpdatingLlmSettings"
                      class="w-full pl-9 pr-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                      @change="handleProviderPresetChange"
                    >
                      <option value="" disabled>选择 LLM 供应商</option>
                      <option v-for="provider in llmProviders" :key="provider.id" :value="provider.id">
                        {{ provider.label }}
                      </option>
                    </select>
                  </div>
                </div>

                <div>
                  <label class="block text-xs font-medium text-slate-700 mb-2">Base URL</label>
                  <input
                    v-model="llmBaseUrl"
                    type="text"
                    placeholder="https://api.example.com/v1"
                    :disabled="isTestingLlm || isUpdatingLlmSettings"
                    class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                </div>

                <div>
                  <label class="block text-xs font-medium text-slate-700 mb-2">模型 ID</label>
                  <input
                    v-model="llmModelId"
                    type="text"
                    placeholder="example-model-id"
                    :disabled="isTestingLlm || isUpdatingLlmSettings"
                    class="w-full px-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  >
                </div>

                <div>
                  <label class="block text-xs font-medium text-slate-700 mb-2">Temperature ({{ llmTemperature }})</label>
                  <input
                    v-model.number="llmTemperature"
                    type="range"
                    min="0"
                    max="2"
                    step="0.1"
                    :disabled="isTestingLlm || isUpdatingLlmSettings"
                    class="w-full h-2 bg-slate-200 rounded-lg appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                  <p class="text-xs text-slate-500 mt-1">控制输出的随机性，0 = 确定性，2 = 最随机</p>
                </div>
              </div>

              <!-- API 密钥 -->
              <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
                <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                  <PhKey :size="18" class="text-blue-500" />
                  <h3 class="text-sm font-semibold text-slate-800">API 密钥</h3>
                </div>

                <div>
                  <label class="block text-xs font-medium text-slate-700 mb-2">API Key</label>
                  <div class="relative">
                    <PhKey :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      v-model="llmApiKey"
                      type="password"
                      placeholder="sk-..."
                      :disabled="isTestingLlm || isUpdatingLlmSettings"
                      class="w-full pl-9 pr-3 py-2.5 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                  </div>
                  <p v-if="llmSettings?.has_api_key" class="text-xs text-emerald-600 mt-2">
                    ✓ 已配置 API Key ({{ llmSettings.api_key_hint }})
                  </p>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="flex gap-3">
                <button
                  @click="handleSaveLlmSettings"
                  :disabled="isTestingLlm || isUpdatingLlmSettings"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <PhSpinner v-if="isUpdatingLlmSettings" :size="16" class="animate-spin" />
                  <span>{{ isUpdatingLlmSettings ? '保存中...' : '保存配置' }}</span>
                </button>
                <button
                  @click="handleTestLlm"
                  :disabled="isTestingLlm || isUpdatingLlmSettings"
                  class="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-emerald-500 hover:bg-emerald-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <PhFlask :size="16" />
                  <span>{{ isTestingLlm ? '测试中...' : '测试连接' }}</span>
                </button>
              </div>
            </div>

          <!-- 转录设置 -->
          <div v-if="settingsTab === 'transcription'" class="space-y-4">
            <!-- 硬件配置 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhCpu :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">硬件配置</h3>
              </div>

              <div v-if="transcriptionSettings" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
                <div class="flex items-center justify-between gap-2 mb-2">
                  <p class="text-sm font-medium text-slate-700">CUDA 状态</p>
                  <span
                    :class="[
                      'text-xs px-2 py-0.5 rounded-full border',
                      transcriptionSettings.cuda_available
                        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                        : 'border-amber-200 bg-amber-50 text-amber-700'
                    ]"
                  >
                    {{ transcriptionSettings.cuda_available ? '可用' : '不可用' }}
                  </span>
                </div>
                <p class="text-xs text-slate-600">
                  {{ transcriptionSettings.cuda_message }}
                </p>
              </div>

              <div>
                <label class="block text-sm font-medium text-slate-700 mb-2">计算设备</label>
                <div class="grid grid-cols-2 gap-3">
                  <button
                    @click="transcriptionDevice = 'cpu'"
                    :class="[
                      'px-4 py-3 rounded-xl border-2 text-left transition-all',
                      transcriptionDevice === 'cpu'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                    ]"
                  >
                    <div class="font-medium">CPU</div>
                    <div class="text-xs text-slate-500 mt-0.5">通用处理器</div>
                  </button>
                  <button
                    @click="transcriptionDevice = 'cuda'"
                    :class="[
                      'px-4 py-3 rounded-xl border-2 text-left transition-all',
                      transcriptionDevice === 'cuda'
                        ? 'border-blue-500 bg-blue-50 text-blue-700'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                    ]"
                    :disabled="!transcriptionSettings?.cuda_available"
                  >
                    <div class="font-medium">CUDA</div>
                    <div class="text-xs text-slate-500 mt-0.5">NVIDIA GPU 加速</div>
                  </button>
                </div>
              </div>
            </div>

            <!-- 模型配置 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhMicrophone :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">模型配置</h3>
              </div>

            <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-3">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-medium text-slate-700">转录模型来源</p>
                <span class="text-xs px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600">
                  {{ transcriptionModelSource === 'auto_download' ? '自动下载' : '手动目录' }}
                </span>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <button
                  @click="transcriptionModelSource = 'auto_download'"
                  :class="[
                    'px-4 py-3 rounded-xl border-2 text-left transition-all',
                    transcriptionModelSource === 'auto_download'
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  ]"
                >
                  <div class="font-medium">自动下载</div>
                  <div class="text-xs text-slate-500 mt-0.5">按模型大小自动加载</div>
                </button>
                <button
                  @click="transcriptionModelSource = 'manual_path'"
                  :class="[
                    'px-4 py-3 rounded-xl border-2 text-left transition-all',
                    transcriptionModelSource === 'manual_path'
                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                      : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300'
                  ]"
                >
                  <div class="font-medium">手动指定目录</div>
                  <div class="text-xs text-slate-500 mt-0.5">使用本地已下载模型</div>
                </button>
              </div>

              <div>
                <label class="block text-xs text-slate-600 mb-1.5">模型大小（自动下载模式）</label>
                <select
                  v-model="transcriptionModelSize"
                  class="w-full px-3 py-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-60"
                  :disabled="transcriptionModelSource !== 'auto_download'"
                >
                  <option value="tiny">tiny</option>
                  <option value="base">base</option>
                  <option value="small">small</option>
                  <option value="medium">medium</option>
                  <option value="large">large</option>
                </select>
              </div>

              <div>
                <label class="block text-xs text-slate-600 mb-1.5">模型目录（手动指定模式）</label>
                <input
                  v-model="transcriptionModelPathInput"
                  type="text"
                  placeholder="例如: E:/models/faster-whisper/tiny"
                  class="w-full px-3 py-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-60"
                  :disabled="transcriptionModelSource !== 'manual_path'"
                >
                <p class="mt-1 text-xs text-slate-500">
                  目录内需包含: {{ requiredModelFilesLabel }}
                </p>
              </div>

              <p
                v-if="transcriptionModelSource === 'manual_path'"
                class="text-xs whitespace-pre-line"
                :class="transcriptionSettings?.model_path_valid ? 'text-emerald-700' : 'text-amber-700'"
              >
                {{ transcriptionSettings?.model_path_message || '手动模式将校验目录完整性。' }}
              </p>
            </div>
            </div>

            <!-- B站字幕配置 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhGitBranch :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">B站字幕配置</h3>
              </div>

              <!-- B站字幕提取 -->
              <div class="flex items-center justify-between gap-3 px-4 py-3 rounded-xl border border-slate-200 bg-slate-50">
              <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-slate-700">优先使用 B 站字幕</p>
                <p class="text-xs text-slate-500 mt-0.5">
                  仅对 B 站链接生效；未获取到字幕时自动回退到下载+ASR
                </p>
              </div>
              <button
                @click="enableBilibiliSubtitleFetch = !enableBilibiliSubtitleFetch"
                :class="[
                  'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                  enableBilibiliSubtitleFetch ? 'bg-blue-500' : 'bg-slate-300'
                ]"
                role="switch"
                :aria-checked="enableBilibiliSubtitleFetch"
              >
                <span
                  :class="[
                    'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                    enableBilibiliSubtitleFetch ? 'translate-x-5' : 'translate-x-0'
                  ]"
                ></span>
              </button>
            </div>

            <!-- B站 SESSDATA -->
            <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 space-y-3">
              <div class="flex items-center justify-between gap-2">
                <p class="text-sm font-medium text-slate-700">全局 B 站 SESSDATA</p>
                <span class="text-xs px-2 py-0.5 rounded-full border border-slate-300 bg-white text-slate-600">
                  来源: {{ bilibiliCookieSourceLabel }}
                </span>
              </div>
              <p class="text-xs text-slate-500">
                当前: {{ transcriptionSettings?.bilibili_sessdata_masked || '未设置' }}
              </p>
              <div class="relative">
                <PhKey :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  v-model="globalBilibiliSessdataInput"
                  type="password"
                  placeholder="输入后保存到本机配置"
                  class="w-full pl-10 pr-3 py-2.5 bg-white border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                >
              </div>
              <p class="text-xs text-amber-600 mt-1">
                提示：如果填写 SESSDATA 后依然获取字幕不成功，请尝试在对应浏览器重新登录或手动复制 SESSDATA。
              </p>
              <div class="grid grid-cols-2 gap-2">
                <button
                  @click="handleReadBilibiliCookieFromBrowser"
                  :disabled="isReadingBilibiliCookieFromBrowser || isUpdatingTranscriptionSettings"
                  class="flex items-center justify-center gap-2 bg-white hover:bg-slate-50 text-slate-600 py-2 rounded-xl text-xs font-medium border border-slate-200 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <PhSpinner v-if="isReadingBilibiliCookieFromBrowser" :size="14" class="animate-spin" />
                  <span>{{ isReadingBilibiliCookieFromBrowser ? '读取中...' : '从浏览器读取' }}</span>
                </button>
                <button
                  @click="clearGlobalBilibiliSessdata"
                  :disabled="isUpdatingTranscriptionSettings || !transcriptionSettings?.has_bilibili_sessdata"
                  class="bg-white hover:bg-slate-50 text-slate-600 py-2 rounded-xl text-xs font-medium border border-slate-200 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  清空已保存 Cookie
                </button>
              </div>
            </div>
            </div>

            <button
              @click="handleSaveTranscriptionSettings"
              :disabled="isUpdatingTranscriptionSettings"
              class="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <PhSpinner v-if="isUpdatingTranscriptionSettings" :size="16" class="animate-spin" />
              <span>{{ isUpdatingTranscriptionSettings ? '保存中...' : '保存设置' }}</span>
            </button>
          </div>

          <!-- Agent 设置 -->
          <div v-if="settingsTab === 'summarization'" class="space-y-4">
            <!-- 使用说明 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-2">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhFlask :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">使用说明</h3>
              </div>
              <p class="text-xs text-slate-600 leading-relaxed">
                长视频会分块总结后拼接。三个参数控制分块大小：<br>
                • 目标时长：期望每块的长度（如30分钟）<br>
                • 最短时长：最后一块的最小长度，太短会合并到前一块（建议为目标的一半）<br>
                • 最长时长：单块的硬性上限（建议为目标的1.3-1.5倍）
              </p>
            </div>

            <!-- 核心参数 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhGitBranch :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">核心参数</h3>
              </div>
              <div class="grid grid-cols-3 gap-3">
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">每块目标时长(分钟)</label>
                  <input
                    v-model.number="chunkTargetDurationSec"
                    type="number"
                    min="0.5"
                    step="0.5"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">每块最短(分钟)</label>
                  <input
                    v-model.number="chunkMinDurationSec"
                    type="number"
                    min="0.5"
                    step="0.5"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">每块最长(分钟)</label>
                  <input
                    v-model.number="chunkMaxDurationSec"
                    type="number"
                    min="0.5"
                    step="0.5"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
              </div>
            </div>

            <!-- 自动触发 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhCpu :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">自动触发</h3>
              </div>
              <p class="text-xs text-slate-500">满足任一条件，就会自动启用 Agent 分块。</p>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">音频时长达到(分钟)</label>
                  <input
                    v-model.number="autoChunkMinAudioDurationSec"
                    type="number"
                    min="5"
                    step="0.5"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">转录行数达到(行)</label>
                  <input
                    v-model.number="autoChunkMinTranscriptLines"
                    type="number"
                    min="100"
                    step="50"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
              </div>
            </div>

            <!-- 高级参数 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhKey :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">高级参数</h3>
              </div>
              <p class="text-xs text-slate-500">一般不用改</p>
              <div class="grid grid-cols-2 gap-3">
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">分块边界容错(秒)</label>
                  <input
                    v-model.number="boundaryJumpSec"
                    type="number"
                    min="1"
                    step="1"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">前文摘要引用上限(字)</label>
                  <input
                    v-model.number="maxAgentValueChars"
                    type="number"
                    min="100"
                    step="50"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                </div>
              </div>

              <!-- 错误回退开关 -->
              <div class="flex items-center justify-between gap-3 pt-2">
                <div class="flex-1 min-w-0">
                  <p class="text-xs font-medium text-slate-700">Agent 失败自动回退标准模式</p>
                  <p class="text-xs text-slate-500 mt-0.5">
                    开启后遇到分块异常会自动降级，保证任务尽量产出结果。
                  </p>
                </div>
                <button
                  @click="fallbackToStandardOnAgentError = !fallbackToStandardOnAgentError"
                  :class="[
                    'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                    fallbackToStandardOnAgentError ? 'bg-blue-500' : 'bg-slate-300'
                  ]"
                  role="switch"
                  :aria-checked="fallbackToStandardOnAgentError"
                >
                  <span
                    :class="[
                      'pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out',
                      fallbackToStandardOnAgentError ? 'translate-x-5' : 'translate-x-0'
                    ]"
                  ></span>
                </button>
              </div>
            </div>

            <!-- 输出目录 -->
            <div class="rounded-xl border border-slate-200 bg-white p-4 space-y-4">
              <div class="flex items-center gap-2 pb-2 border-b border-slate-100">
                <PhFolderOpen :size="18" class="text-blue-500" />
                <h3 class="text-sm font-semibold text-slate-800">输出目录</h3>
              </div>
              <p class="text-xs text-slate-500">设置转录文件和总结文件的保存目录，支持相对路径（基于项目根目录）或绝对路径。</p>
              <div class="space-y-3">
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">转录文件保存目录</label>
                  <input
                    v-model="transcriptDir"
                    type="text"
                    placeholder="例如: temp 或 /absolute/path/to/transcripts"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono"
                  >
                  <p class="text-xs text-slate-400 mt-1">转录文本（字幕原文）的保存位置，默认为 temp</p>
                </div>
                <div>
                  <label class="block text-xs text-slate-600 mb-1.5">总结文件保存目录</label>
                  <input
                    v-model="summaryDir"
                    type="text"
                    placeholder="例如: temp 或 /absolute/path/to/summaries"
                    class="w-full px-3 py-2 bg-slate-50 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono"
                  >
                  <p class="text-xs text-slate-400 mt-1">AI 总结文章的保存位置，默认为 temp</p>
                </div>
              </div>
            </div>

            <button
              @click="handleSaveSummarizationSettings"
              :disabled="isUpdatingSummarizationSettings"
              class="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <PhSpinner v-if="isUpdatingSummarizationSettings" :size="16" class="animate-spin" />
              <span>{{ isUpdatingSummarizationSettings ? '保存中...' : '保存设置' }}</span>
            </button>
          </div>
          </div>
        </div>
      </div>

      <!-- 移动端底部退出按钮 -->
      <button
        @click="emit('close')"
        class="md:hidden flex items-center justify-center gap-2 px-6 py-3 text-white text-sm font-medium transition-opacity hover:opacity-80"
      >
        <PhX :size="20" />
        <span>关闭</span>
      </button>
    </div>
  </Transition>
</template>

<style scoped>
.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 200ms ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

.modal-fade-enter-active > div,
.modal-fade-leave-active > div {
  transition: transform 200ms ease, opacity 200ms ease;
}

.modal-fade-enter-from > div,
.modal-fade-leave-to > div {
  transform: scale(0.95);
  opacity: 0;
}

.custom-scrollbar::-webkit-scrollbar {
  width: 6px;
}

.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}

.custom-scrollbar::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}

.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}

input[type="range"]::-webkit-slider-thumb {
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
}

input[type="range"]::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #3b82f6;
  cursor: pointer;
  border: none;
}
</style>
