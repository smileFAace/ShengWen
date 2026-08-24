<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  PhWaveSine,
  PhLink,
  PhUpload,
  PhSpinner,
  PhCheckCircle,
  PhXCircle,
  PhClock,
  PhX,
  PhTrash,
  PhInfo,
  PhKey,
  PhGearSix,
  PhMagnifyingGlass,
  PhFolder,
  PhFloppyDisk,
  PhFlask,
  PhPlayCircle,
  PhLightning,
  PhBrain,
  PhFile,
  PhQuestion,
} from '@phosphor-icons/vue'
import {
  TaskStatus,
  type Task,
  type SummaryMode,
  type LLMProvider,
  type LLMSettings,
  type TranscriptionSettings,
  type SummarizationSettings,
  type Folder,
  type FolderTreeNode,
} from '../types'
import ThemeSelector from './ThemeSelector.vue'
import FolderBrowser from './FolderBrowser/FolderBrowser.vue'

const videoUrl = defineModel<string>('videoUrl', { required: true })
const selectedFile = defineModel<File | null>('selectedFile', { default: null })
const localFilePath = defineModel<string>('localFilePath', { default: '' })
// const quality = defineModel<string>('quality', { required: true })
const summaryMode = defineModel<Exclude<SummaryMode, 'auto'>>('summaryMode', { default: 'standard' })
const isSidebarOpen = defineModel<boolean>('isSidebarOpen', { required: true })

const props = defineProps<{
  isLocalClient: boolean
  isPrewarming: boolean
  tasks: Task[]
  selectedTask: Task | null
  isSubmitting: boolean
  llmProviders: LLMProvider[]
  llmSettings: LLMSettings | null
  activeProfileId: string
  editingProfileId: string
  profileFormState: { name: string; provider: string; base_url: string; model_id: string; temperature: number; api_key: string }
  isUpdatingLlmSettings: boolean
  isTestingLlm: boolean
  isSwitchingProfile: boolean
  transcriptionSettings: TranscriptionSettings | null
  isUpdatingTranscriptionSettings: boolean
  summarizationSettings: SummarizationSettings | null
  isUpdatingSummarizationSettings: boolean
  folders: Folder[]
  folderTree: FolderTreeNode[]
  isMultiSelectMode: boolean
  selectedTaskIds: Set<string>
}>()

const emit = defineEmits<{
  submit: []
  cancelSubmit: []
  selectTask: [task: Task]
  deleteTask: [taskId: string]
  showInfo: [task: Task]
  openSettings: []
  createFolder: [name: string, parentId: string | null]
  renameFolder: [folderId: string, newName: string]
  deleteFolder: [folderId: string]
  assignTaskToFolder: [taskId: string, folderId: string | null]
  moveFolder: [folderId: string, newParentId: string | null]
  toggleMultiSelectMode: []
  toggleTaskSelection: [taskId: string]
  selectAllTasks: []
  clearSelection: []
  batchReSummarize: [taskIds: string[]]
  batchReTranscribe: [taskIds: string[]]
  batchDownloadMarkdown: [taskIds: string[]]
  batchDelete: [taskIds: string[]]
  toggleFolderSelection: [taskIds: string[], selected: boolean]
  focusSearchMatch: [payload: {
    taskId: string
    keyword: string
    source: SearchMatchSource
    requestId: number
  }]
  updateLlmSettings: [payload: {
    profile_id: string
    name?: string
    provider?: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  }]
  switchActiveProfile: [profileId: string]
  editProfile: [profileId: string]
  createProfile: [name: string, provider: string]
  deleteProfile: [profileId: string]
  updateTranscriptionSettings: [payload: {
    device?: 'cpu' | 'cuda'
    model_source?: 'auto_download' | 'manual_path'
    model_size?: 'tiny' | 'base' | 'small' | 'medium' | 'large'
    model_path?: string
    compute_type_mode?: 'auto' | 'manual'
    compute_type?: 'int8' | 'float16' | 'float32' | 'bfloat16'
    enable_bilibili_subtitle_fetch?: boolean
    bilibili_sessdata?: string
    clear_bilibili_sessdata?: boolean
  }]
  updateSummarizationSettings: [payload: {
    chunk_target_duration_sec?: number
    chunk_min_duration_sec?: number
    chunk_max_duration_sec?: number
    boundary_jump_sec?: number
    auto_chunk_min_audio_duration_sec?: number
    auto_chunk_min_transcript_lines?: number
    max_agent_value_chars?: number
    fallback_to_standard_on_agent_error?: boolean
  }]
  startTestLlm: []
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const isSettingsPanelOpen = ref(false)
const settingsTab = ref<'llm' | 'transcription' | 'summarization'>('llm')
const sidebarTab = ref<'quick' | 'manage' | 'theme'>('quick')
const showLocalPathHelp = ref(false)

const llmApiKey = ref('')
const llmBaseUrl = computed({
  get: () => props.profileFormState.base_url,
  set: (v: string) => { props.profileFormState.base_url = v },
})
const llmModelId = computed({
  get: () => props.profileFormState.model_id,
  set: (v: string) => { props.profileFormState.model_id = v },
})
const llmTemperature = computed({
  get: () => props.profileFormState.temperature,
  set: (v: number) => { props.profileFormState.temperature = v },
})
const appVersion = __APP_VERSION__

const transcriptionDevice = ref<'cpu' | 'cuda'>('cpu')
const transcriptionModelSource = ref<'auto_download' | 'manual_path'>('auto_download')
const transcriptionModelSize = ref<'tiny' | 'base' | 'small' | 'medium' | 'large'>('tiny')
const transcriptionModelPathInput = ref('')
const transcriptionComputeTypeMode = ref<'auto' | 'manual'>('auto')
const transcriptionComputeType = ref<'int8' | 'float16' | 'float32' | 'bfloat16'>('int8')
const enableBilibiliSubtitleFetch = ref(true)
const globalBilibiliSessdataInput = ref('')
const chunkTargetDurationSec = ref(20)
const chunkMinDurationSec = ref(10)
const chunkMaxDurationSec = ref(30)
const boundaryJumpSec = ref(10)
const autoChunkMinAudioDurationSec = ref(40)
const autoChunkMinTranscriptLines = ref(1800)
const maxAgentValueChars = ref(500)
const fallbackToStandardOnAgentError = ref(true)

const secondsToMinutes = (seconds: number) => {
  return Math.round((Number(seconds || 0) / 60) * 10) / 10
}

const minutesToSeconds = (minutes: number) => {
  return Math.round(Number(minutes || 0) * 60)
}

const manageKeyword = ref('')
const manageStatus = ref<'all' | TaskStatus>('all')
const manageSort = ref<'newest' | 'oldest' | 'latest_modified'>('newest')
const searchRequestId = ref(0)

type MatchPreview = {
  hasHit: boolean
  before: string
  hit: string
  after: string
  leftEllipsis: boolean
  rightEllipsis: boolean
}

type ManagedTaskResult = {
  task: Task
  topicPreview: MatchPreview
  summaryPreview: MatchPreview
  modifiedLabel: string
  modifiedTitle: string
}

type SearchMatchSource = 'topic' | 'summary'

const triggerFileUpload = () => {
  fileInput.value?.click()
}

const switchSummaryMode = (mode: Exclude<SummaryMode, 'auto'>) => {
  summaryMode.value = mode
}

const handleSubmitAction = () => {
  if (props.isSubmitting) {
    emit('cancelSubmit')
    return
  }
  emit('submit')
}

const handleVideoUrlEnter = () => {
  if (props.isSubmitting) return
  if (!videoUrl.value.trim()) return
  handleSubmitAction()
}

const handleLocalPathEnter = () => {
  if (props.isSubmitting) return
  if (!localFilePath.value.trim()) return
  handleSubmitAction()
}

const handleFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (file) {
    // 清空 URL 输入框（互斥模式）
    videoUrl.value = ''
    localFilePath.value = ''
    selectedFile.value = file
  }
}

const handleLocalPathInput = (event: Event) => {
  selectedFile.value = null
  videoUrl.value = ''

  // 自动清理路径格式
  const input = event.target as HTMLInputElement
  let value = input.value

  // 去除首尾空格和引号
  value = value.trim()
  if ((value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))) {
    value = value.slice(1, -1)
  }

  // 更新清理后的值
  if (value !== input.value) {
    localFilePath.value = value
  }
}

const handleClearSelectedFile = () => {
  if (props.isSubmitting) {
    emit('cancelSubmit')
  }
  selectedFile.value = null
}

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

const resolveTaskTopic = (task: Task) => {
  return task.topic || (task.summary && task.summary.match(/\{\{topic:?\s*(.*?)\}\}/i)?.[1]) || task.title || task.video_url
}

const emptyPreview = (): MatchPreview => ({
  hasHit: false,
  before: '',
  hit: '',
  after: '',
  leftEllipsis: false,
  rightEllipsis: false,
})

const buildMatchPreview = (text: string, keyword: string, context = 18): MatchPreview => {
  const source = (text || '').replace(/\s+/g, ' ').trim()
  const q = keyword.trim()
  if (!source || !q) return emptyPreview()

  const sourceLower = source.toLowerCase()
  const qLower = q.toLowerCase()
  const idx = sourceLower.indexOf(qLower)
  if (idx < 0) return emptyPreview()

  const start = Math.max(0, idx - context)
  const end = Math.min(source.length, idx + q.length + context)
  return {
    hasHit: true,
    before: source.slice(start, idx),
    hit: source.slice(idx, idx + q.length),
    after: source.slice(idx + q.length, end),
    leftEllipsis: start > 0,
    rightEllipsis: end < source.length,
  }
}

const editingProfile = computed(() => {
  if (!props.llmSettings) return null
  return props.llmSettings.profiles.find(p => p.id === props.editingProfileId)
})

const syncLlmSettings = (_settings: LLMSettings | null) => {
  llmApiKey.value = ''
}

const syncTranscriptionSettings = (settings: TranscriptionSettings | null) => {
  if (!settings) return
  transcriptionDevice.value = settings.device
  transcriptionModelSource.value = settings.model_source
  transcriptionModelSize.value = settings.model_size
  transcriptionModelPathInput.value = settings.model_path
  transcriptionComputeTypeMode.value = settings.compute_type_mode || 'auto'
  transcriptionComputeType.value = settings.manual_compute_type || settings.compute_type || 'int8'
  enableBilibiliSubtitleFetch.value = settings.enable_bilibili_subtitle_fetch
}

const syncSummarizationSettings = (settings: SummarizationSettings | null) => {
  if (!settings) return
  chunkTargetDurationSec.value = secondsToMinutes(settings.chunk_target_duration_sec)
  chunkMinDurationSec.value = secondsToMinutes(settings.chunk_min_duration_sec)
  chunkMaxDurationSec.value = secondsToMinutes(settings.chunk_max_duration_sec)
  boundaryJumpSec.value = settings.boundary_jump_sec
  autoChunkMinAudioDurationSec.value = secondsToMinutes(settings.auto_chunk_min_audio_duration_sec)
  autoChunkMinTranscriptLines.value = settings.auto_chunk_min_transcript_lines
  maxAgentValueChars.value = settings.max_agent_value_chars
  fallbackToStandardOnAgentError.value = settings.fallback_to_standard_on_agent_error
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

const submitLlmSettings = () => {
  if (!llmBaseUrl.value || !llmModelId.value) return

  const payload: {
    profile_id: string
    name?: string
    provider?: string
    base_url?: string
    api_key?: string
    model_id?: string
    temperature?: number
  } = {
    profile_id: props.editingProfileId,
    provider: props.profileFormState.provider,
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

const submitTranscriptionSettings = () => {
  const payload: {
    device?: 'cpu' | 'cuda'
    model_source?: 'auto_download' | 'manual_path'
    model_size?: 'tiny' | 'base' | 'small' | 'medium' | 'large'
    model_path?: string
    compute_type_mode?: 'auto' | 'manual'
    compute_type?: 'int8' | 'float16' | 'float32' | 'bfloat16'
    enable_bilibili_subtitle_fetch?: boolean
    bilibili_sessdata?: string
  } = {
    device: transcriptionDevice.value,
    model_source: transcriptionModelSource.value,
    model_size: transcriptionModelSize.value,
    model_path: transcriptionModelPathInput.value.trim(),
    compute_type_mode: transcriptionComputeTypeMode.value,
    compute_type: transcriptionComputeType.value,
    enable_bilibili_subtitle_fetch: enableBilibiliSubtitleFetch.value
  }
  const cookie = globalBilibiliSessdataInput.value.trim()
  if (cookie) {
    payload.bilibili_sessdata = cookie
  }
  emit('updateTranscriptionSettings', payload)
  globalBilibiliSessdataInput.value = ''
}

const submitSummarizationSettings = () => {
  const minSec = Math.max(30, minutesToSeconds(chunkMinDurationSec.value))
  const maxSec = Math.max(minSec, minutesToSeconds(chunkMaxDurationSec.value))
  const targetSec = Math.min(Math.max(minutesToSeconds(chunkTargetDurationSec.value), minSec), maxSec)
  const autoAudioSec = Math.max(300, minutesToSeconds(autoChunkMinAudioDurationSec.value))

  chunkMinDurationSec.value = secondsToMinutes(minSec)
  chunkMaxDurationSec.value = secondsToMinutes(maxSec)
  chunkTargetDurationSec.value = secondsToMinutes(targetSec)
  autoChunkMinAudioDurationSec.value = secondsToMinutes(autoAudioSec)

  emit('updateSummarizationSettings', {
    chunk_target_duration_sec: targetSec,
    chunk_min_duration_sec: minSec,
    chunk_max_duration_sec: maxSec,
    boundary_jump_sec: Math.max(1, Number(boundaryJumpSec.value || 0)),
    auto_chunk_min_audio_duration_sec: autoAudioSec,
    auto_chunk_min_transcript_lines: Math.max(100, Number(autoChunkMinTranscriptLines.value || 0)),
    max_agent_value_chars: Math.max(100, Number(maxAgentValueChars.value || 0)),
    fallback_to_standard_on_agent_error: fallbackToStandardOnAgentError.value,
  })
}

const clearGlobalBilibiliSessdata = () => {
  globalBilibiliSessdataInput.value = ''
  emit('updateTranscriptionSettings', { clear_bilibili_sessdata: true })
}

const handleTestLlm = async () => {
  try {
    // 先保存配置
    await submitLlmSettings()
    // 再触发测试
    emit('startTestLlm')
  } catch (err) {
    // 保存失败时不触发测试
  }
}

const getStatusLabel = (status: TaskStatus) => {
  switch (status) {
    case TaskStatus.COMPLETED: return '完成'
    case TaskStatus.FAILED: return '失败'
    case TaskStatus.PENDING: return '等待中'
    case TaskStatus.DOWNLOADING: return '下载中'
    case TaskStatus.UPLOADING: return '上传中'
    case TaskStatus.TRANSCRIBING: return '转录中'
    case TaskStatus.SUMMARIZING: return '总结中'
    default: return status
  }
}

const getTaskStatusLabel = (task: Task) => {
  if (task.status !== TaskStatus.SUMMARIZING) {
    return getStatusLabel(task.status)
  }
  const total = Number(task.summary_chunk_total || 0)
  const done = Number(task.summary_chunk_done || 0)
  if (total > 0) {
    return `总结中 (${Math.min(done, total)}/${total})`
  }
  return '总结中'
}

const getStatusClass = (status: TaskStatus) => {
  switch (status) {
    case TaskStatus.COMPLETED: return 'text-emerald-600 bg-emerald-50'
    case TaskStatus.FAILED: return 'text-red-600 bg-red-50'
    case TaskStatus.PENDING: return 'text-slate-400 bg-slate-50'
    default: return 'text-blue-600 bg-blue-50'
  }
}

const getStatusIcon = (status: TaskStatus) => {
  switch (status) {
    case TaskStatus.COMPLETED: return PhCheckCircle
    case TaskStatus.FAILED: return PhXCircle
    case TaskStatus.PENDING: return PhClock
    default: return PhSpinner
  }
}

const formatTaskDate = (dateString: string) => {
  const date = new Date(dateString)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()

  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  }

  return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
}

const formatTaskDateTime = (dateString: string) => {
  const date = new Date(dateString)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleString([], {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit'
  })
}

const buildModifiedInfo = (task: Task) => {
  const modifiedRaw = task.latest_modified_at
  if (!modifiedRaw) {
    return { label: '', title: '' }
  }

  const modifiedAt = new Date(modifiedRaw)
  const createdAt = new Date(task.created_at)
  if (Number.isNaN(modifiedAt.getTime()) || Number.isNaN(createdAt.getTime())) {
    return { label: '', title: '' }
  }

  // 与创建时间几乎一致则不显示，避免视觉噪音。
  if (Math.abs(modifiedAt.getTime() - createdAt.getTime()) < 60 * 1000) {
    return { label: '', title: '' }
  }

  const now = new Date()
  if (modifiedAt.toDateString() === now.toDateString()) {
    return {
      label: `改 ${modifiedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
      title: formatTaskDateTime(modifiedRaw)
    }
  }

  return {
    label: `改 ${modifiedAt.toLocaleDateString([], { month: '2-digit', day: '2-digit' })}`,
    title: formatTaskDateTime(modifiedRaw)
  }
}

const statusOptions: Array<{ value: 'all' | TaskStatus, label: string }> = [
  { value: 'all', label: '全部状态' },
  { value: TaskStatus.PENDING, label: '等待中' },
  { value: TaskStatus.DOWNLOADING, label: '下载中' },
  { value: TaskStatus.UPLOADING, label: '上传中' },
  { value: TaskStatus.TRANSCRIBING, label: '转录中' },
  { value: TaskStatus.SUMMARIZING, label: '总结中' },
  { value: TaskStatus.COMPLETED, label: '完成' },
  { value: TaskStatus.FAILED, label: '失败' },
]

const managedResults = computed<ManagedTaskResult[]>(() => {
  const keyword = manageKeyword.value.trim()
  const status = manageStatus.value
  let list = props.tasks.map((task) => {
    const topicPreview = buildMatchPreview(resolveTaskTopic(task), keyword, 14)
    const summaryPreview = buildMatchPreview(task.summary || '', keyword, 22)
    const modifiedInfo = buildModifiedInfo(task)
    return {
      task,
      topicPreview,
      summaryPreview,
      modifiedLabel: modifiedInfo.label,
      modifiedTitle: modifiedInfo.title,
    }
  })

  if (keyword) {
    list = list.filter((item) => item.topicPreview.hasHit || item.summaryPreview.hasHit)
  }

  if (status !== 'all') {
    list = list.filter((item) => item.task.status === status)
  }

  list.sort((a, b) => {
    const modifiedA = new Date(a.task.latest_modified_at || a.task.created_at).getTime()
    const modifiedB = new Date(b.task.latest_modified_at || b.task.created_at).getTime()
    const ta = new Date(a.task.created_at).getTime()
    const tb = new Date(b.task.created_at).getTime()
    if (manageSort.value === 'latest_modified') return modifiedB - modifiedA
    if (manageSort.value === 'oldest') return ta - tb
    return tb - ta
  })

  return list
})

const handleManagedResultClick = (result: ManagedTaskResult) => {
  emit('selectTask', result.task)
  isSidebarOpen.value = false

  const keyword = manageKeyword.value.trim()
  if (!keyword) return

  let source: SearchMatchSource | null = null
  if (result.summaryPreview.hasHit) {
    source = 'summary'
  } else if (result.topicPreview.hasHit) {
    source = 'topic'
  }

  if (!source) return
  searchRequestId.value += 1
  emit('focusSearchMatch', {
    taskId: result.task.id,
    keyword,
    source,
    requestId: searchRequestId.value,
  })
}

watch(() => props.llmSettings, (settings) => {
  syncLlmSettings(settings)
}, { immediate: true })

watch(() => props.transcriptionSettings, (settings) => {
  syncTranscriptionSettings(settings)
}, { immediate: true })

watch(() => props.summarizationSettings, (settings) => {
  syncSummarizationSettings(settings)
}, { immediate: true })
</script>

<template>
  <aside
    :class="[
      'fixed md:static inset-y-0 left-0 z-40 w-[85%] max-w-[340px] md:w-[400px] bg-white border-r border-gray-100 h-full shadow-2xl md:shadow-none transition-transform duration-300 transform',
      isSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
    ]"
  >
    <div class="flex h-full">
      <!-- 左侧 tab rail -->
      <div class="w-14 shrink-0 border-r border-gray-100 bg-gray-50 flex flex-col items-center py-4 gap-2">
        <button
          @click="sidebarTab = 'quick'"
          :class="[
            'w-10 h-10 rounded-xl flex items-center justify-center transition-colors',
            sidebarTab === 'quick'
              ? 'bg-blue-50 text-primary'
              : 'text-slate-400 hover:bg-gray-100 hover:text-slate-600'
          ]"
          title="任务管理"
        >
          <PhFolder :size="20" />
        </button>

        <button
          @click="sidebarTab = 'manage'"
          :class="[
            'w-10 h-10 rounded-xl flex items-center justify-center transition-colors relative',
            sidebarTab === 'manage'
              ? 'bg-blue-50 text-primary'
              : 'text-slate-400 hover:bg-gray-100 hover:text-slate-600'
          ]"
          title="任务搜索"
        >
          <PhMagnifyingGlass :size="20" />
          <span class="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-gray-200 text-slate-500 text-[10px] leading-4 text-center">
            {{ tasks.length }}
          </span>
        </button>
      </div>

      <div class="flex-1 min-w-0 flex flex-col">
        <div class="relative">
          <!-- Logo -->
          <div class="p-4 border-b border-gray-100 flex items-center justify-between">
            <div class="flex items-center gap-2.5 min-w-0">
              <div class="w-9 h-9 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl flex items-center justify-center text-white shadow-sm shadow-blue-200 shrink-0">
                <PhWaveSine :size="20" weight="bold" />
              </div>
              <div class="min-w-0">
                <h1 class="text-lg font-bold text-slate-900 tracking-tight truncate">声文智汇</h1>
                <p class="text-[11px] text-slate-500">
                  {{ sidebarTab === 'quick' ? '快速提交与任务浏览' : sidebarTab === 'manage' ? '全部任务搜索视图' : 'Markdown 样式主题' }} · v{{ appVersion }}
                </p>
              </div>
            </div>

            <div class="flex items-center gap-1">
              <button
                @click="emit('openSettings')"
                class="w-8 h-8 rounded-lg border border-slate-200 bg-white text-slate-400 hover:text-blue-600 hover:border-blue-200 hover:bg-blue-50 transition-colors flex items-center justify-center"
                title="设置"
              >
                <PhGearSix :size="16" />
              </button>
              <button @click="isSidebarOpen = false" class="md:hidden text-slate-400 hover:text-slate-600 p-1">
                <PhX :size="20" />
              </button>
            </div>
          </div>

          <Transition name="settings-pop">
            <div
              v-if="isSettingsPanelOpen"
              class="mx-4 mt-3 rounded-2xl border border-gray-100 bg-white shadow-lg p-3 max-h-[52dvh] overflow-y-auto relative z-20 md:absolute md:top-[72px] md:left-4 md:right-4 md:mx-0 md:mt-0 md:max-h-[70dvh] md:z-30"
            >
              <div class="grid grid-cols-3 gap-1 p-1 bg-slate-100 rounded-xl mb-3">
                <button
                  @click="settingsTab = 'llm'"
                  :class="[
                    'py-1.5 text-xs font-medium rounded-lg transition-colors',
                    settingsTab === 'llm' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  ]"
                >
                  LLM
                </button>
                <button
                  @click="settingsTab = 'transcription'"
                  :class="[
                    'py-1.5 text-xs font-medium rounded-lg transition-colors',
                    settingsTab === 'transcription' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  ]"
                >
                  转录
                </button>
                <button
                  @click="settingsTab = 'summarization'"
                  :class="[
                    'py-1.5 text-xs font-medium rounded-lg transition-colors',
                    settingsTab === 'summarization' ? 'bg-white text-slate-800 shadow-sm' : 'text-slate-500 hover:text-slate-700'
                  ]"
                >
                  Agent
                </button>
              </div>

              <div v-if="settingsTab === 'llm'" class="space-y-2.5">
                <!-- Profile selector (compact) -->
                <div class="flex gap-1.5 overflow-x-auto">
                  <button
                    v-for="profile in llmSettings?.profiles || []"
                    :key="profile.id"
                    @click="emit('switchActiveProfile', profile.id)"
                    :disabled="props.isSwitchingProfile || props.isTestingLlm || props.isUpdatingLlmSettings"
                    :class="[
                      'px-2.5 py-1.5 rounded-lg text-xs font-medium border transition-all whitespace-nowrap flex items-center gap-1.5',
                      props.activeProfileId === profile.id
                        ? 'border-blue-300 bg-blue-50 text-blue-700'
                        : 'border-gray-200 bg-white text-slate-500 hover:border-gray-300'
                    ]"
                  >
                    <span>{{ profile.name }}</span>
                    <span v-if="profile.has_api_key" class="w-1.5 h-1.5 rounded-full bg-emerald-400 inline-block"></span>
                  </button>
                </div>

                <input
                  v-model="llmBaseUrl"
                  type="text"
                  placeholder="Base URL"
                  :disabled="props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile"
                  class="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >

                <input
                  v-model="llmModelId"
                  type="text"
                  placeholder="模型 ID"
                  :disabled="props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile"
                  class="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >

                <input
                  v-model.number="llmTemperature"
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  placeholder="Temperature"
                  :disabled="props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile"
                  class="w-full px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
                >

                <div class="relative">
                  <PhKey :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                  <input
                    v-model="llmApiKey"
                    type="password"
                    placeholder="留空则保持当前 API Key"
                    :disabled="props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile"
                    class="w-full pl-10 pr-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                </div>

                <p v-if="editingProfile?.has_api_key" class="text-[11px] text-slate-500">
                  当前 API Key: {{ editingProfile?.api_key_hint }}
                </p>

                <div class="space-y-2 pt-1">
                  <button
                    @click="submitLlmSettings"
                    :disabled="props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile || !llmBaseUrl || !llmModelId"
                    class="w-full bg-slate-800 hover:bg-slate-700 text-white py-2.5 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    <PhFloppyDisk :size="16" weight="fill" />
                    <span v-if="props.isUpdatingLlmSettings">保存中...</span>
                    <span v-else>保存配置</span>
                  </button>
                  <button
                    @click="handleTestLlm"
                    :disabled="props.isPrewarming || props.isTestingLlm || props.isUpdatingLlmSettings || props.isSwitchingProfile || !llmBaseUrl || !llmModelId"
                    class="w-full bg-blue-500 hover:bg-blue-600 text-white py-2.5 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
                  >
                    <PhSpinner v-if="props.isPrewarming" :size="16" class="animate-spin" />
                    <PhSpinner v-else-if="props.isTestingLlm" :size="16" class="animate-spin" />
                    <PhFlask v-else :size="16" weight="fill" />
                    <span v-if="props.isPrewarming">初始化中...</span>
                    <span v-else-if="props.isTestingLlm">测试中...</span>
                    <span v-else>测试模型</span>
                  </button>
                </div>
              </div>

              <div v-else-if="settingsTab === 'transcription'" class="space-y-2.5">
                <div
                  v-if="props.transcriptionSettings"
                  class="rounded-xl border border-gray-200 bg-gray-50 px-3 py-2.5"
                >
                  <div class="flex items-center justify-between gap-2">
                    <p class="text-xs font-medium text-slate-700">CUDA 诊断</p>
                    <span
                      :class="[
                        'text-[10px] px-2 py-0.5 rounded-full border',
                        props.transcriptionSettings.cuda_available
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                          : 'border-amber-200 bg-amber-50 text-amber-700'
                      ]"
                    >
                      {{ props.transcriptionSettings.cuda_available ? '可用' : '不可用' }}
                    </span>
                  </div>
                  <p class="mt-1 text-[11px] text-slate-500">
                    NVIDIA: {{ props.transcriptionSettings.has_nvidia_gpu ? '已检测' : '未检测' }} ·
                    PyTorch CUDA: {{ props.transcriptionSettings.torch_cuda_built ? '已启用' : '未启用' }} ·
                    CTranslate2: {{
                      props.transcriptionSettings.ctranslate2_installed
                        ? `已安装 (GPU=${props.transcriptionSettings.ctranslate2_cuda_device_count})`
                        : '未安装'
                    }}
                  </p>
                  <p
                    class="mt-1.5 text-[11px] whitespace-pre-line"
                    :class="props.transcriptionSettings.cuda_available ? 'text-emerald-700' : 'text-amber-700'"
                  >
                    {{ props.transcriptionSettings.cuda_message }}
                  </p>
                </div>

                <button
                  @click="transcriptionDevice = 'cpu'"
                  :class="[
                    'w-full px-3 py-2.5 rounded-lg border text-sm text-left transition-colors',
                    transcriptionDevice === 'cpu'
                      ? 'border-primary/40 bg-blue-50 text-slate-800'
                      : 'border-gray-200 bg-gray-50 text-slate-600 hover:bg-gray-100'
                  ]"
                >
                  CPU 转录
                </button>
                <button
                  @click="transcriptionDevice = 'cuda'"
                  :disabled="!props.transcriptionSettings?.cuda_available"
                  :class="[
                    'w-full px-3 py-2.5 rounded-lg border text-sm text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60',
                    transcriptionDevice === 'cuda'
                      ? 'border-primary/40 bg-blue-50 text-slate-800'
                      : 'border-gray-200 bg-gray-50 text-slate-600 hover:bg-gray-100'
                  ]"
                >
                  CUDA 转录
                </button>

                <div class="rounded-xl border border-gray-200 bg-gray-50/60 px-3 py-3 space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <p class="text-sm font-medium text-slate-700">计算精度策略</p>
                    <span class="text-[10px] px-2 py-0.5 rounded-full border border-slate-200 bg-white text-slate-500">
                      生效: {{ props.transcriptionSettings?.compute_type || 'int8' }}
                    </span>
                  </div>
                  <div class="grid grid-cols-2 gap-2">
                    <button
                      @click="transcriptionComputeTypeMode = 'auto'"
                      :class="[
                        'px-3 py-2 rounded-lg border text-xs text-left transition-colors',
                        transcriptionComputeTypeMode === 'auto'
                          ? 'border-primary/40 bg-blue-50 text-slate-800'
                          : 'border-gray-200 bg-white text-slate-600 hover:bg-gray-100'
                      ]"
                    >
                      自动
                    </button>
                    <button
                      @click="transcriptionComputeTypeMode = 'manual'"
                      :class="[
                        'px-3 py-2 rounded-lg border text-xs text-left transition-colors',
                        transcriptionComputeTypeMode === 'manual'
                          ? 'border-primary/40 bg-blue-50 text-slate-800'
                          : 'border-gray-200 bg-white text-slate-600 hover:bg-gray-100'
                      ]"
                    >
                      手动
                    </button>
                  </div>
                  <select
                    v-model="transcriptionComputeType"
                    :disabled="transcriptionComputeTypeMode !== 'manual'"
                    class="w-full px-2.5 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-60"
                  >
                    <option v-for="option in (props.transcriptionSettings?.available_compute_types || ['int8'])" :key="option" :value="option">
                      {{ option }}
                    </option>
                  </select>
                </div>

                <div class="rounded-xl border border-gray-200 bg-gray-50/60 px-3 py-3 space-y-2.5">
                  <div class="flex items-center justify-between gap-2">
                    <p class="text-sm font-medium text-slate-700">转录模型来源</p>
                    <span class="text-[10px] px-2 py-0.5 rounded-full border border-slate-200 bg-white text-slate-500">
                      {{ transcriptionModelSource === 'auto_download' ? '自动下载' : '手动目录' }}
                    </span>
                  </div>

                  <div class="grid grid-cols-2 gap-2">
                    <button
                      @click="transcriptionModelSource = 'auto_download'"
                      :class="[
                        'px-3 py-2 rounded-lg border text-xs text-left transition-colors',
                        transcriptionModelSource === 'auto_download'
                          ? 'border-primary/40 bg-blue-50 text-slate-800'
                          : 'border-gray-200 bg-white text-slate-600 hover:bg-gray-100'
                      ]"
                    >
                      自动下载
                    </button>
                    <button
                      @click="transcriptionModelSource = 'manual_path'"
                      :class="[
                        'px-3 py-2 rounded-lg border text-xs text-left transition-colors',
                        transcriptionModelSource === 'manual_path'
                          ? 'border-primary/40 bg-blue-50 text-slate-800'
                          : 'border-gray-200 bg-white text-slate-600 hover:bg-gray-100'
                      ]"
                    >
                      手动目录
                    </button>
                  </div>

                  <div>
                    <label class="block text-[11px] text-slate-500 mb-1">模型大小（自动下载）</label>
                    <select
                      v-model="transcriptionModelSize"
                      :disabled="transcriptionModelSource !== 'auto_download'"
                      class="w-full px-2.5 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-60"
                    >
                      <option value="tiny">tiny</option>
                      <option value="base">base</option>
                      <option value="small">small</option>
                      <option value="medium">medium</option>
                      <option value="large">large</option>
                    </select>
                  </div>

                  <div>
                    <label class="block text-[11px] text-slate-500 mb-1">模型目录（手动指定）</label>
                    <input
                      v-model="transcriptionModelPathInput"
                      type="text"
                      placeholder="E:/models/faster-whisper/tiny"
                      :disabled="transcriptionModelSource !== 'manual_path'"
                      class="w-full px-2.5 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary disabled:opacity-60"
                    >
                    <p class="mt-1 text-[11px] text-slate-500">
                      需包含: {{ requiredModelFilesLabel }}
                    </p>
                  </div>

                  <p
                    v-if="transcriptionModelSource === 'manual_path'"
                    class="text-[11px] whitespace-pre-line"
                    :class="props.transcriptionSettings?.model_path_valid ? 'text-emerald-700' : 'text-amber-700'"
                  >
                    {{ props.transcriptionSettings?.model_path_message || '手动模式将校验目录完整性。' }}
                  </p>
                </div>

                <div class="flex items-center justify-between gap-3 px-3 py-3 rounded-xl border border-gray-200 bg-gray-50/50">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-slate-700">优先使用 B 站字幕</p>
                    <p class="text-[11px] text-slate-500 leading-relaxed mt-0.5">
                      仅对 B 站链接生效；未获取到字幕时自动回退到下载+ASR
                    </p>
                  </div>
                  <button
                    @click="enableBilibiliSubtitleFetch = !enableBilibiliSubtitleFetch"
                    :class="[
                      'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                      enableBilibiliSubtitleFetch ? 'bg-blue-500' : 'bg-gray-300'
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

                <div class="rounded-xl border border-gray-200 bg-gray-50/60 px-3 py-3 space-y-2">
                  <div class="flex items-center justify-between gap-2">
                    <p class="text-sm font-medium text-slate-700">全局 B 站 SESSDATA</p>
                    <span class="text-[10px] px-2 py-0.5 rounded-full border border-slate-200 bg-white text-slate-500">
                      来源: {{ bilibiliCookieSourceLabel }}
                    </span>
                  </div>
                  <p class="text-[11px] text-slate-500">
                    当前: {{ props.transcriptionSettings?.bilibili_sessdata_masked || '未设置' }}
                  </p>
                  <div class="relative">
                    <PhKey :size="15" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      v-model="globalBilibiliSessdataInput"
                      type="password"
                      placeholder="输入后保存到本机配置"
                      class="w-full pl-9 pr-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                    >
                  </div>
                  <button
                    @click="clearGlobalBilibiliSessdata"
                    :disabled="props.isUpdatingTranscriptionSettings || !props.transcriptionSettings?.has_bilibili_sessdata"
                    class="w-full bg-white hover:bg-gray-100 text-slate-600 py-1.5 rounded-lg text-xs font-medium border border-gray-200 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    清空已保存 Cookie
                  </button>
                </div>

                <button
                  @click="submitTranscriptionSettings"
                  :disabled="props.isUpdatingTranscriptionSettings"
                  class="w-full bg-slate-800 hover:bg-slate-700 text-white py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span v-if="props.isUpdatingTranscriptionSettings">保存中...</span>
                  <span v-else>保存转录配置</span>
                </button>
              </div>

              <div v-else class="space-y-3">
                <div class="rounded-xl border border-blue-100 bg-blue-50/60 px-3 py-3">
                  <p class="text-sm font-semibold text-slate-800">Agent 分块怎么调</p>
                  <p class="mt-1 text-[12px] text-slate-600 leading-relaxed">
                    长视频会先切成几段再总结。先调“每块目标时长”，推荐 15~25 分钟。
                  </p>
                </div>

                <div class="space-y-2">
                  <p class="text-[11px] font-medium uppercase tracking-wide text-slate-500">核心参数</p>
                  <div class="grid grid-cols-3 gap-2">
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">每块目标时长(分钟)</span>
                      <input
                        v-model.number="chunkTargetDurationSec"
                        type="number"
                        min="0.5"
                        step="0.5"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">每块最短(分钟)</span>
                      <input
                        v-model.number="chunkMinDurationSec"
                        type="number"
                        min="0.5"
                        step="0.5"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">每块最长(分钟)</span>
                      <input
                        v-model.number="chunkMaxDurationSec"
                        type="number"
                        min="0.5"
                        step="0.5"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                  </div>
                </div>

                <div class="space-y-2">
                  <p class="text-[11px] font-medium uppercase tracking-wide text-slate-500">自动分块触发</p>
                  <p class="text-[11px] text-slate-500">满足任一条件，就会自动启用 Agent 分块。</p>
                  <div class="grid grid-cols-2 gap-2">
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">音频时长达到(分钟)</span>
                      <input
                        v-model.number="autoChunkMinAudioDurationSec"
                        type="number"
                        min="5"
                        step="0.5"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">转录行数达到(行)</span>
                      <input
                        v-model.number="autoChunkMinTranscriptLines"
                        type="number"
                        min="100"
                        step="50"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                  </div>
                </div>

                <div class="space-y-2">
                  <p class="text-[11px] font-medium uppercase tracking-wide text-slate-500">高级参数(一般不用改)</p>
                  <div class="grid grid-cols-2 gap-2">
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">分块边界容错(秒)</span>
                      <input
                        v-model.number="boundaryJumpSec"
                        type="number"
                        min="1"
                        step="1"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                    <label class="space-y-1">
                      <span class="text-[11px] text-slate-500">前文摘要引用上限(字)</span>
                      <input
                        v-model.number="maxAgentValueChars"
                        type="number"
                        min="100"
                        step="50"
                        class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
                      >
                    </label>
                  </div>
                </div>

                <div class="flex items-center justify-between gap-3 px-3 py-3 rounded-xl border border-gray-200 bg-gray-50/50">
                  <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-slate-700">Agent 失败自动回退标准模式</p>
                    <p class="text-[11px] text-slate-500 leading-relaxed mt-0.5">
                      开启后遇到分块异常会自动降级，保证任务尽量产出结果。
                    </p>
                  </div>
                  <button
                    @click="fallbackToStandardOnAgentError = !fallbackToStandardOnAgentError"
                    :class="[
                      'relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2',
                      fallbackToStandardOnAgentError ? 'bg-blue-500' : 'bg-gray-300'
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

                <button
                  @click="submitSummarizationSettings"
                  :disabled="props.isUpdatingSummarizationSettings"
                  class="w-full bg-slate-800 hover:bg-slate-700 text-white py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span v-if="props.isUpdatingSummarizationSettings">保存中...</span>
                  <span v-else>保存 Agent 配置</span>
                </button>
              </div>
            </div>
          </Transition>
        </div>

        <template v-if="sidebarTab === 'quick'">
          <!-- 提交新任务 -->
          <div class="p-3 pb-2">
            <div class="space-y-2.5">
              <div class="relative">
                <PhLink :size="18" class="absolute left-3 top-3 text-slate-400" />
                <input
                  v-model="videoUrl"
                  type="text"
                  placeholder="粘贴视频 URL (如 Bilibili)"
                  class="w-full pl-10 pr-12 py-2.5 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-sm"
                  @input="selectedFile = null; localFilePath = ''"
                  @keydown.enter.prevent="handleVideoUrlEnter"
                >
                <button
                  @click="triggerFileUpload"
                  class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-slate-400 hover:text-primary hover:bg-blue-50 rounded-lg transition-colors"
                  title="上传音视频或字幕/文稿文件（.srt/.vtt/.ass/.ssa/.txt）"
                >
                  <PhUpload :size="18" />
                </button>
                <input
                  ref="fileInput"
                  type="file"
                  accept="video/*,audio/*,.srt,.vtt,.ass,.ssa,.txt"
                  class="hidden"
                  @change="handleFileChange"
                >
              </div>

              <div
                v-if="props.isLocalClient"
                class="flex items-center gap-1.5 px-1 mt-3 mb-1"
              >
                <span class="text-xs font-medium text-slate-600">根据本地文件路径创建</span>
                <button
                  @click="showLocalPathHelp = !showLocalPathHelp"
                  class="p-0.5 text-slate-400 hover:text-primary hover:bg-blue-50 rounded transition-colors"
                  title="如何复制本地文件路径"
                >
                  <PhQuestion :size="14" weight="bold" />
                </button>
              </div>

              <!-- 帮助提示 -->
              <div
                v-if="props.isLocalClient && showLocalPathHelp"
                class="mx-1 mb-2 p-2.5 bg-blue-50 border border-blue-100 rounded-lg text-xs text-slate-600 space-y-1"
              >
                <p class="font-medium text-slate-700">快速复制文件路径：</p>
                <p>• Windows: 按住 <kbd class="px-1 py-0.5 bg-white border border-slate-300 rounded text-[10px] font-mono">Shift</kbd> + 右键文件 → "复制为路径"</p>
                <p>• 或直接从文件管理器地址栏复制完整路径</p>
              </div>

              <div
                v-if="props.isLocalClient"
                class="relative"
              >
                <PhFile :size="18" class="absolute left-3 top-3 text-slate-400" />
                <input
                  v-model="localFilePath"
                  type="text"
                  placeholder="粘贴本机文件路径"
                  class="w-full pl-10 pr-10 py-2.5 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-sm"
                  @input="handleLocalPathInput"
                  @keydown.enter.prevent="handleLocalPathEnter"
                >
                <button
                  v-if="localFilePath"
                  @click="localFilePath = ''"
                  class="absolute right-2 top-1/2 -translate-y-1/2 p-1.5 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
                  title="清空路径"
                >
                  <PhX :size="16" />
                </button>
              </div>

              <div v-if="selectedFile" class="flex items-center gap-2 px-3 py-2 bg-blue-50 border border-blue-100 rounded-lg text-sm">
                <div class="flex-1 min-w-0">
                  <p class="font-medium text-slate-700 truncate">{{ selectedFile.name }}</p>
                  <p class="text-xs text-slate-500">{{ formatFileSize(selectedFile.size) }}</p>
                </div>
                <button
                  @click="handleClearSelectedFile"
                  class="p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 rounded transition-colors"
                  title="清除文件"
                >
                  <PhX :size="16" />
                </button>
              </div>

              <p class="px-1 text-[11px] leading-4 text-slate-400">
                支持音视频（.mp4/.mp3 等）或字幕/文稿（.srt/.vtt/.ass/.ssa/.txt）
              </p>

              <div class="relative">
                <div class="relative flex bg-gray-100 p-1 rounded-2xl transition-all duration-200 overflow-visible">
                  <div
                    class="absolute top-1 bottom-1 w-[calc(50%-4px)] rounded-xl transition-all duration-300 ease-out"
                    :class="summaryMode === 'standard'
                      ? 'left-1 bg-white shadow-sm'
                      : 'left-[calc(50%)] agent-gradient shadow-[0_8px_24px_rgba(59,130,246,0.35)]'"
                  ></div>

                  <div
                    class="pointer-events-none absolute -right-3 -bottom-3 h-10 w-28 rounded-full agent-glow blur-xl transition-opacity duration-300"
                    :class="summaryMode === 'agent' ? 'opacity-100' : 'opacity-0'"
                  ></div>

                  <button
                    type="button"
                    @click="switchSummaryMode('standard')"
                    class="relative z-10 flex-1 px-3 py-2 rounded-xl text-xs font-medium transition-colors inline-flex items-center justify-center gap-1.5"
                    :class="summaryMode === 'standard' ? 'text-primary' : 'text-slate-500 hover:text-slate-700'"
                  >
                    <PhLightning :size="13" :weight="summaryMode === 'standard' ? 'fill' : 'regular'" />
                    <span>标准模式</span>
                  </button>
                  <button
                    type="button"
                    @click="switchSummaryMode('agent')"
                    class="relative z-10 flex-1 px-3 py-2 rounded-xl text-xs font-medium transition-colors inline-flex items-center justify-center gap-1.5"
                    :class="summaryMode === 'agent' ? 'text-white' : 'text-slate-500 hover:text-slate-700'"
                  >
                    <PhBrain :size="13" :weight="summaryMode === 'agent' ? 'fill' : 'regular'" />
                    <span>Agent 模式</span>
                  </button>
                </div>
              </div>

              <button
                @click="handleSubmitAction"
                :disabled="props.isPrewarming || (!isSubmitting && !videoUrl && !selectedFile && !localFilePath)"
                class="w-full bg-primary hover:bg-secondary text-white py-2.5 rounded-xl font-semibold transition-all shadow-sm shadow-blue-100 flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed active:scale-95"
              >
                <PhSpinner v-if="props.isPrewarming" :size="18" class="animate-spin" />
                <PhSpinner v-else-if="isSubmitting" :size="18" class="animate-spin" />
                <PhPlayCircle v-else :size="18" />
                {{ props.isPrewarming ? '正在初始化...' : isSubmitting ? '取消提交' : '开始处理' }}
              </button>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-4 custom-scrollbar">
            <FolderBrowser
              :tasks="tasks"
              :folders="folders"
              :folderTree="folderTree"
              :selectedTask="selectedTask"
              :multiSelectMode="isMultiSelectMode"
              :selectedTaskIds="selectedTaskIds"
              @selectTask="(task) => { emit('selectTask', task); if (!isMultiSelectMode) isSidebarOpen = false; }"
              @deleteTask="emit('deleteTask', $event)"
              @showInfo="emit('showInfo', $event)"
              @createFolder="(name: any, parentId: any) => emit('createFolder', name, parentId)"
              @renameFolder="(folderId: any, newName: any) => emit('renameFolder', folderId, newName)"
              @deleteFolder="emit('deleteFolder', $event)"
              @assignTaskToFolder="(taskId: any, folderId: any) => emit('assignTaskToFolder', taskId, folderId)"
              @moveFolder="(folderId: any, newParentId: any) => emit('moveFolder', folderId, newParentId)"
              @toggleMultiSelectMode="emit('toggleMultiSelectMode')"
              @toggleTaskSelection="emit('toggleTaskSelection', $event)"
              @selectAllTasks="emit('selectAllTasks')"
              @clearSelection="emit('clearSelection')"
              @batchReSummarize="emit('batchReSummarize', $event)"
              @batchReTranscribe="emit('batchReTranscribe', $event)"
              @batchDownloadMarkdown="emit('batchDownloadMarkdown', $event)"
              @batchDelete="emit('batchDelete', $event)"
              @toggleFolderSelection="(ids: any, selected: any) => emit('toggleFolderSelection', ids, selected)"
            />
          </div>
        </template>

        <template v-else>
          <!-- 管理任务 -->
          <div class="p-4 pb-3 border-b border-gray-100 space-y-2.5">
            <h2 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">任务搜索</h2>
            <div class="relative">
              <PhMagnifyingGlass :size="16" class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                v-model="manageKeyword"
                type="text"
                placeholder="搜索 topic / AI 总结正文"
                class="w-full pl-9 pr-3 py-2 bg-gray-50 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              >
            </div>
            <div class="grid grid-cols-2 gap-2">
              <select
                v-model="manageStatus"
                class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              >
                <option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
              <select
                v-model="manageSort"
                class="w-full px-2.5 py-2 bg-gray-50 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary"
              >
                <option value="newest">最新优先</option>
                <option value="latest_modified">最新修改优先</option>
                <option value="oldest">最早优先</option>
              </select>
            </div>
          </div>

          <div class="flex-1 overflow-y-auto p-4 custom-scrollbar">
            <div class="text-[11px] text-slate-400 mb-2 px-1">共 {{ managedResults.length }} 条</div>
            <div class="space-y-2">
              <div
                v-for="result in managedResults"
                :key="result.task.id"
                @click="handleManagedResultClick(result)"
                :class="['p-2.5 rounded-xl border cursor-pointer transition-all hover:shadow-sm active:scale-[0.985] relative',
                         selectedTask?.id === result.task.id ? 'border-blue-200 bg-blue-50/60 ring-1 ring-primary/20 shadow-sm' : 'border-gray-100 hover:bg-white hover:border-gray-200']"
              >
                <div class="flex justify-between items-start gap-2 mb-1">
                  <span :class="['text-[11px] font-medium px-1.5 py-0.5 rounded-full flex items-center gap-1 shrink-0', getStatusClass(result.task.status)]">
                    <component :is="getStatusIcon(result.task.status)" :size="12" :class="result.task.status !== TaskStatus.COMPLETED && result.task.status !== TaskStatus.FAILED && result.task.status !== TaskStatus.PENDING ? 'animate-spin' : ''" />
                    {{ getTaskStatusLabel(result.task) }}
                  </span>
                  <div class="flex items-center gap-1.5 shrink-0">
                    <span class="text-[10px] text-slate-400">{{ formatTaskDate(result.task.created_at) }}</span>
                    <span
                      v-if="result.modifiedLabel"
                      :title="result.modifiedTitle"
                      class="text-[10px] text-slate-500 bg-slate-100 px-1.5 py-[1px] rounded-md border border-slate-200/80"
                    >
                      {{ result.modifiedLabel }}
                    </span>
                  </div>
                </div>
                <div class="text-[13px] leading-5 font-medium text-slate-700 line-clamp-2" :title="result.task.title || result.task.video_url">
                  {{ result.task.title || result.task.video_url }}
                </div>
                <div v-if="result.task.topic" class="text-[11px] text-slate-400 truncate mt-0.5" :title="result.task.topic">
                  {{ result.task.topic }}
                </div>

                <div v-if="manageKeyword.trim()" class="mt-1.5 space-y-0.5">
                  <div v-if="result.topicPreview.hasHit" class="flex items-start gap-1 text-[10px] text-slate-500">
                    <span class="px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 shrink-0">主题</span>
                    <p class="leading-[1.15rem] break-all">
                      <span v-if="result.topicPreview.leftEllipsis">...</span>{{ result.topicPreview.before }}<mark class="bg-amber-200/80 px-0.5 rounded">{{ result.topicPreview.hit }}</mark>{{ result.topicPreview.after }}<span v-if="result.topicPreview.rightEllipsis">...</span>
                    </p>
                  </div>
                  <div v-if="result.summaryPreview.hasHit" class="flex items-start gap-1 text-[10px] text-slate-500">
                    <span class="px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 shrink-0">正文</span>
                    <p class="leading-[1.15rem] break-all">
                      <span v-if="result.summaryPreview.leftEllipsis">...</span>{{ result.summaryPreview.before }}<mark class="bg-amber-200/80 px-0.5 rounded">{{ result.summaryPreview.hit }}</mark>{{ result.summaryPreview.after }}<span v-if="result.summaryPreview.rightEllipsis">...</span>
                    </p>
                  </div>
                </div>

                <div class="mt-1.5 flex items-center justify-end gap-1">
                  <button
                    @click.stop="emit('showInfo', result.task)"
                    class="text-slate-400 hover:text-blue-500 p-0.5"
                    title="查看信息"
                  >
                    <PhInfo :size="13" />
                  </button>
                  <button
                    @click.stop="emit('deleteTask', result.task.id)"
                    class="text-slate-400 hover:text-red-500 p-0.5"
                    title="删除任务"
                  >
                    <PhTrash :size="13" />
                  </button>
                </div>
              </div>
              <p v-if="managedResults.length === 0" class="text-center text-gray-400 py-8 text-sm">没有匹配的任务</p>
            </div>
          </div>
        </template>

        <!-- 主题选择器 -->
        <template v-if="sidebarTab === 'theme'">
          <ThemeSelector />
        </template>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.settings-pop-enter-active,
.settings-pop-leave-active {
  transition: opacity 180ms ease, transform 180ms ease;
}

.settings-pop-enter-from,
.settings-pop-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}

/* Agent 模式极光流动动画 */
@keyframes aurora-flow {
  0% {
    background-position: 0% 50%;
    background-size: 180% 180%;
  }
  15% {
    background-position: 30% 20%;
    background-size: 220% 200%;
  }
  33% {
    background-position: 80% 30%;
    background-size: 200% 240%;
  }
  50% {
    background-position: 100% 70%;
    background-size: 190% 190%;
  }
  67% {
    background-position: 60% 100%;
    background-size: 230% 210%;
  }
  85% {
    background-position: 20% 80%;
    background-size: 200% 220%;
  }
  100% {
    background-position: 0% 50%;
    background-size: 180% 180%;
  }
}

.agent-gradient {
  background: linear-gradient(
    125deg,
    #06b6d4,
    #3b82f6,
    #5b8ff9,
    #3b82f6,
    #6366f1,
    #3b82f6,
    #06b6d4
  );
  background-size: 180% 180%;
  animation: aurora-flow 12s ease-in-out infinite;
}

.agent-glow {
  background: linear-gradient(
    125deg,
    rgba(6, 182, 212, 0.25),
    rgba(59, 130, 246, 0.3),
    rgba(91, 143, 249, 0.28),
    rgba(59, 130, 246, 0.3),
    rgba(99, 102, 241, 0.22),
    rgba(59, 130, 246, 0.3),
    rgba(6, 182, 212, 0.25)
  );
  background-size: 180% 180%;
  animation: aurora-flow 12s ease-in-out infinite;
}
</style>

